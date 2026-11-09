# Unified MTH evidence model

**Status:** normative documentation only. This file defines an evidence contract;
it does not create a new runtime, schema file, deployment, or CI run.

**Baseline:** commit `12980a3` (2026-11-08). Counts and results in this document
are frozen at that tracked commit. Modified or untracked files in a working tree
are not part of the baseline and cannot be promoted by citing this document. If
the baseline commit changes, re-baseline the counts before reusing any claim.

**Baseline counts**

| Item | Count |
|---|---:|
| Catalogued MTH kernels in `spec/wave-capabilities.json` | 155 |
| Kernels with `ci_verified=true` in the manifest | 145 |
| Unique native sources | 153 |
| Unique manifest fixture files | 151 |
| Fixture entries in the canonical runner | 152 |
| Native-dispatch ABI kernels | 5 |
| Local Python tests | 1,452+ |
| Universe pages / NaN16 words / relation points | 256 / 1,048,576 / 32,896 |
| Providers in the unified system spec | 7 (3 required, 4 optional) |

**Non-claims.** This document does **not** claim:

- a live Koyeb deployment, a live NANNET0 service, or live MTH execution;
- that a production signed volume registry exists, or that any cryptographic
  signature or HMAC has been verified against production material;
- that CI was re-run while preparing this document;
- that any fixture, catalog, or CI result proves mathematical truth beyond the
  marker and artifact it actually records.

The run identifiers cited below are recorded in
`docs/R10_IMPLEMENTATION_EVIDENCE.md` and `docs/MTH_UNIFIED_SYSTEM.md`. They are
historical CI records, not results freshly reproduced here.

## 1. The five evidence classes

One evidence model means one envelope, one status vocabulary, and one
invalidation law. It does **not** mean one combined green status. The five
classes answer different questions and are not interchangeable.

| ID | Evidence class | Question answered | Primary producer | Primary artifacts |
|---|---|---|---|---|
| E1 | Local native fixture | Did the exact NaN16 source pass its own fixture with the named toolchain? | `tools/run_mth_fixtures.py` | manifest, native source, fixture, local runner log |
| E2 | Canonical CI | Did the canonical GitHub Actions workflow pass on the exact commit? | canonical NaNROUTER workflows | workflow file, run ID, commit, job log |
| E3 | Cross-repo provider contract | Are the declared provider artifacts and contract strings present in a worktree or fetched `origin/main`? | `tools/mth_unified.py` | unified system spec, provider audit, catalog digest |
| E4 | Signed volume-registry | Is a generation-chained, HMAC-authenticated volume registry valid and are all four canonical tier volumes mounted and healthy at observation time? | `runner_riddle/volume_registry.py` and the registry operator | signed registry payload, trust root, verification report |
| E5 | Live deployment | Is a specific deployed build serving the recorded endpoint and executing the recorded MTH path? | deployment operator | deployment ID, health/point-0 transcripts, ring/JAHS snapshot, logs |

### 1.1 Separation rules

1. **No substitution.** A green result in one class never creates a green result
   in another. Local PASS is not CI. CI is not live. A provider checkout is not
   a deployment. A catalog is not a signature. A signed volume registry is not
   proof that MTH executed.
2. **Subject binding.** Every record is bound to a subject digest, a commit, and
   a toolchain. If the subject changes, the record becomes stale even if the
   old log still exists.
3. **No inference from absence.** Missing evidence is `unknown` or `blocked`,
   never green. Missing CI logs do not become a pass; a missing registry does not
   become a healthy volume; a missing deployment transcript does not become a
   live service.
4. **Scope is part of the claim.** “Green” always means green for a named class,
   subject, commit, generation, and observation window. An unqualified “MTH is
   green” is forbidden.
5. **Tracked state only.** Uncommitted or untracked work may be measured
   locally, but it cannot promote a manifest entry, a CI claim, a provider
   contract, or a deployment claim.

## 2. Common evidence record

Every class uses the same envelope. The envelope is a documentary contract in
this document; it is not an additional tracked schema file at the baseline
commit.

```json
{
  "schema": "nanrouter.unified-mth-evidence.v1",
  "evidence_id": "sha256:<canonical-record-digest>",
  "class": "local_native_fixture | canonical_ci | provider_contract | signed_volume_registry | live_deployment",
  "subject": {
    "kind": "mth_kernel | manifest | provider | volume_registry | deployment",
    "id": "mth.universe.map.u32",
    "version": 1,
    "digests": {
      "source_sha256": "<64 hex>",
      "fixture_sha256": "<64 hex>"
    }
  },
  "scope": "single fixture PASS marker",
  "producer": {
    "tool": "tools/run_mth_fixtures.py",
    "tool_sha256": "<64 hex>",
    "operator": "<identity or automation>"
  },
  "source": {
    "repo": "NaNROUTER",
    "commit": "<40 hex>",
    "tree": "<40 hex>",
    "ref": "refs/heads/main",
    "dirty": false
  },
  "environment": {
    "os": "<platform>",
    "nan0s_commit": "<40 hex>",
    "assembler": "nan0s/tools/nmk.awk",
    "vm": "nan0s/aarch64/android/nan_cli"
  },
  "command": ["python3", "tools/run_mth_fixtures.py", "--only", "universe_map"],
  "artifacts": [
    {"path": "mth/tests/mth_universe_map_test.nas", "sha256": "<64 hex>"}
  ],
  "result": {
    "status": "green",
    "marker": "MTH UNIVERSE MAP PASS",
    "steps_budget": 13000000,
    "steps_observed": 12916386,
    "exit_code": 0
  },
  "limitations": [
    "local execution only",
    "PASS marker is a guest self-check, not an independent numerical oracle"
  ],
  "observed_at": "2026-11-08T00:00:00Z",
  "valid_until": null,
  "supersedes": null
}
```

### 2.1 Common required fields

| Field | Requirement |
|---|---|
| `schema` | Exact string `nanrouter.unified-mth-evidence.v1` |
| `evidence_id` | SHA-256 of the canonical record with `evidence_id` omitted |
| `class` | Exactly one of the five class identifiers |
| `subject` | Kind, stable ID, version, and all subject digests |
| `scope` | The precise claim boundary, including what is excluded |
| `producer` | Tool path, tool digest, operator/automation identity |
| `source` | Repository, commit, tree, ref, and dirty state |
| `environment` | Host/runtime/toolchain identity needed to reproduce the result |
| `command` | Exact command or workflow invocation |
| `artifacts` | Every inspected or executed artifact with SHA-256 |
| `result` | Status plus class-specific result fields |
| `limitations` | Explicit non-guarantees |
| `observed_at` | Observation time; not the time the document was written |
| `valid_until` | Expiry or `null`; live evidence must state a validity window |
| `supersedes` | Prior `evidence_id` or `null`; history is append-only |

### 2.2 Status vocabulary

| Status | Meaning | Promotion effect |
|---|---|---|
| `green` | All required fields are present; the class check passed for the exact subject, commit, and scope | May support the class-specific claim only |
| `blocked` | A required external input or check is missing or failed | Cannot promote; must be reported as blocked |
| `unknown` | No usable evidence exists or it cannot be inspected | Cannot promote; never treated as green |
| `stale` | Evidence exists but the subject, generation, toolchain, or observation window changed | Must be re-established before reuse |
| `invalid` | Digest mismatch, tamper, schema violation, or contradictory evidence | Cannot promote; investigate before replacing |
| `superseded` | A newer record exists for the same subject and scope | Retained for history; not current |

`blocked` and `unknown` are deliberately different. `blocked` means a known
external gate is absent or failed. `unknown` means the evidence cannot even be
classified. Neither is green.

### 2.3 Integrity rule

`evidence_id` protects record integrity, not truth. It proves that the record
was not altered after issuance. It does not prove that a deployment exists, that
a fixture used the right oracle, or that a provider is live.

## 3. E1 — Local native fixture evidence

### 3.1 What this class establishes

`tools/run_mth_fixtures.py` assembles a NaN16 fixture with the canonical NaN0S
assembler, runs it in `nan_cli`, and checks the fixture's declared PASS marker.
The runner does not calculate expected mathematical results on the guest's
behalf. A green local record therefore establishes:

- the exact fixture was assembled and executed;
- the guest emitted the exact PASS marker within the step budget;
- the recorded source, fixture, runner, assembler, and VM digests match.

It does not establish numerical equivalence to an independent oracle, CI
status, provider deployment, or live execution.

### 3.2 Required fields

In addition to the common envelope:

| Field | Requirement |
|---|---|
| `kernel_id` | Manifest kernel ID, or explicit `runner_only` fixture label |
| `source.path` / `source.sha256` | NaN16 source and digest |
| `fixture.path` / `fixture.sha256` | NaN16 fixture and digest |
| `marker` | Exact expected PASS marker |
| `steps_budget` | Step limit used by the runner |
| `steps_observed` | Guest-reported step count, if emitted |
| `assembler` | `nan0s/tools/nmk.awk` plus digest or commit |
| `vm` | `nan0s/aarch64/android/nan_cli` plus digest or commit |
| `command` | Exact runner invocation, including `--only` names |
| `exit_code` | Runner and guest process status |
| `stdout_sha256` / `stderr_sha256` | Log digests or retained log references |
| `repo_head` / `repo_dirty` | Local repository state at observation |
| `manifest_sha256` | Manifest used to select the kernel |
| `runner_sha256` | Canonical runner used for the execution |

A record with a PASS marker but no artifact digests is not promotable. A record
from a dirty worktree is `local_dirty`; it may be reported as local evidence but
cannot promote a tracked manifest entry.

### 3.3 Baseline counts and how they reconcile

At baseline commit `12980a3`:

- `spec/wave-capabilities.json` contains **127 catalogued kernels**.
- Those 127 entries reference **125 unique native sources** and **124 unique
  fixture files**; some kernels intentionally share a source or fixture.
- `tools/run_mth_fixtures.py` contains **110 fixture entries**: the 109 unique
  manifest fixtures plus one runner-only dispatch fixture,
  `mth/tests/mth_native_vector_addsub_dispatch_test.nas`. That fixture is
  declared in `spec/nan-native-boundary.json` as runner-only and exercises
  dispatch over already-registered vector kernels; it is not a 97th kernel.
- The manifest declares **155/155 `ci_verified=true`**. That is a ledger field,
  not a substitute for the E2 run record.
- The recorded local suite is **1,452+ local Python tests** (baseline record:
  `Ran 1452 tests`, `OK (skipped=30)`).
- The full universe-map fixture passes locally in **12,916,386 guest steps**;
  it is one fixture, not all 155 kernels.

The excluded `mth/nan16/mth_graph_path_witness.nas` is a separate candidate
witness with its own gate and is not an authorized numerical MTH kernel. The
catalogued `mth.graph.claim_probe.u32` is a bounded candidate query, not a proof
or promotion authority.

### 3.4 Promotion rules

1. `source_written` may become `native_verified` only after a local fixture PASS
   with all required E1 fields, matching source/fixture digests, and a green
   static coverage audit.
2. E1 can never set `ci_verified=true`. Only E2 can do that.
3. E1 cannot add a new catalog entry by itself. A new kernel also needs a
   manifest entry, source/fixture registration, layer assignment, runner entry,
   and audit coverage.
4. A local PASS on a dirty or untracked tree is recorded as local evidence but
   is excluded from promotion until the exact artifacts are committed.
5. A local PASS for one fixture promotes only that kernel/fixture subject. It
   does not promote sibling kernels, the manifest as a whole, or the universe
   map.

**Baseline E1 result:** recorded local runner evidence is 110/110 PASS against
NaN0S `f31143e`; the canonical workflow pin `fe63617` differs only in a CI
workflow file according to `docs/R10_IMPLEMENTATION_EVIDENCE.md`. This is still
local evidence, not a fresh E2 claim.

### 3.5 Invalidation rules

A local record becomes `stale` or `invalid` when any of the following changes:

- the source or fixture content digest;
- the marker, step budget, observed step count, or runner behavior;
- `tools/run_mth_fixtures.py`, the assembler, or the VM;
- the NaN0S toolchain commit or build options;
- the manifest entry, kernel version, layer assignment, or catalog digest;
- the repository commit/tree used for promotion;
- the record's logs or digests are missing or contradictory.

Changing a kernel requires re-running its fixture. Changing the runner or
toolchain invalidates the whole local set and requires a new run; old step
counts may be retained only as historical evidence.

### 3.6 Forbidden E1 claims

- “Local PASS proves the mathematics is correct.” It proves the fixture's own
  assertions and PASS marker passed.
- “Local PASS is CI-verified.”
- “Local PASS means the service is live.”
- “152 runner fixtures means 155 kernels were executed.” The counts measure
  different things and one fixture can serve multiple kernel entries.
- “All 155 kernels ran in every local invocation.”
- “An untracked kernel is catalogued.”
- “A route or address mapping proves a mathematical relation.”
- “The runner independently verifies numerical results.” The runner checks a
  marker; the fixture contains the guest-side assertions.

## 4. E2 — Canonical CI evidence

### 4.1 Definition of canonical

Canonical CI means a GitHub Actions run in the repository's own workflow,
executed from a tracked workflow file at the recorded commit, with the subject
commit reachable from `main`. A local `act` run, a fork run, a manually
transcribed result, or a run on an unrelated commit is not canonical CI.

The unified system spec already states the rule: only canonical GitHub Actions
results are CI-verified.

### 4.2 Required fields

In addition to the common envelope:

| Field | Requirement |
|---|---|
| `repository` | `shemshallah/NaNROUTER` (or the exact authorized repo) |
| `workflow.path` / `workflow.sha256` | Workflow file and digest at the run commit |
| `run_id` / `run_attempt` | GitHub Actions identifiers |
| `event` / `ref` | Trigger and exact ref |
| `commit_sha` / `tree_sha` | Exact subject commit and tree |
| `job_name` | Job that executed the subject |
| `runner_image` | `ubuntu-latest` or exact runner identity |
| `toolchain_pin` | NaN0S commit used by that workflow |
| `command` | Exact fixture/test invocation |
| `started_at` / `completed_at` | Run timestamps |
| `conclusion` | `success` required for promotion |
| `log_reference` / `log_sha256` | Retained log or artifact reference |
| `subjects` | Fixture names, test modules, or artifacts actually exercised |

A manifest `ci_verified=true` without an E2 record is a declared ledger value,
not evidence.

### 4.3 What each canonical workflow actually covers

| Workflow | Coverage scope |
|---|---|
| `.github/workflows/mth-native-contract.yml` | Explicit native fixture steps, pinned NaN0S `fe63617`; not automatically all 125 runner entries |
| `.github/workflows/mth-remaining-fixtures.yml` | The 31-fixture remaining promotion set, pinned NaN0S `fe63617` |
| `.github/workflows/mth-native-addsub-dispatch.yml` | Add/sub dispatch and linker regression fixtures plus `test_hermes_mth_tools.py`, pinned NaN0S `fe63617` |
| `.github/workflows/native-graph-claim-probe.yml` | The separately gated claim-probe fixture, pinned NaN0S `7f250a11` |
| `.github/workflows/mth-unified-audit.yml` | Universe-map check, unified-catalog check, and two focused test modules; no native fixture execution |
| `.github/workflows/manifest-contract.yml` | Full Python test discovery and manifest contract checks |
| `.github/workflows/koyeb-container-smoke.yml` | Credential-free container build and `/healthz` contract; no Koyeb credentials and no live deployment |

Therefore, one green workflow does not imply all 155 kernels, all 152 runner
fixtures, or a live service.

### 4.4 Baseline CI records

The following runs are recorded in the repository history. They are listed to
identify the baseline evidence, not as a claim that this document re-ran them.

| Workflow | Recorded run | Recorded scope |
|---|---|---|
| `mth-native-contract` | `42405649076` | 61-fixture set, 132 steps |
| `mth-remaining-fixtures` | `42547371933` | 47-fixture remaining promotion set, including stable numerics and sequence |
| `native-graph-claim-probe` | `42539739728` | Graph claim-probe fixture |
| `mth-remaining-fixtures` | `42542521347` | Re-pass of the remaining set on `0fdb60c` |
| `mth-native-contract` | `42542521393` | Native contract set |
| `manifest-contract` | `42542521540` | Full manifest contract / test suite |
| `koyeb-container-smoke` | `42542521266` | Credential-free container smoke |
| `mth-unified-audit` | `42542831186` | Universe-map and unified-catalog checks |

The 155/155 `ci_verified` declaration in the manifest is supported by these
recorded canonical runs, not by the existence of the boolean itself.

### 4.5 Promotion rules

1. Only a canonical E2 `success` on the exact subject commit may set
   `ci_verified=true` or `status=ci_verified`.
2. A local PASS, a provider audit, a container smoke, or a manifest edit cannot
   set `ci_verified=true`.
3. A green run that did not execute the subject fixture/test does not promote
   that subject.
4. A run on a commit that is not the promotion commit, or from a fork, is not
   canonical for promotion.
5. A workflow change, runner change, toolchain pin change, or subject change
   requires a new run.
6. The promotion record must name the run ID, workflow, commit, and job. A
   boolean without those fields is not promotable.

### 4.6 Invalidation rules

A CI record becomes `stale` or `unknown` when:

- the subject source, fixture, manifest, runner, or workflow changes;
- the pinned toolchain changes;
- the commit is rewritten or the branch history is replaced;
- the run is cancelled, failed, neutral, or skipped;
- the run was produced in a non-canonical repository/fork;
- the logs/artifacts have expired and cannot be re-inspected;
- the workflow no longer exists or no longer executes the subject.

Log expiry does not retroactively turn a historical success into a failure, but
it means the record is `recorded-unverified` for any new promotion decision. It
cannot be cited as freshly verified CI.

### 4.7 Forbidden E2 claims

- “CI is live deployment.”
- “A green `mth-unified-audit` run proves all native fixtures.”
- “A green container smoke proves Koyeb is running.”
- “The manifest says `ci_verified`, so the kernel is CI-verified” without a run
  record.
- “A local pass is a CI pass.”
- “CI proves numerical correctness beyond the executed fixture and marker.”
- “A run on a branch or fork is canonical for `main`.”

## 5. E3 — Cross-repo provider contract evidence

### 5.1 What this class establishes

`spec/mth-unified-system.v1.json` declares providers, required artifacts, and
textual contracts. `tools/mth_unified.py` inspects those contracts in a local
worktree or in a fetched `origin/main` blob without fetching, checking out,
resetting, or rewriting the sibling repository. A green provider audit means:

- the declared artifact paths exist;
- the declared contract strings are present;
- the inspected source (`worktree` or `origin/main`) is recorded;
- the provider status is `available`.

It does not mean the provider is built, deployed, reachable, or executing the
same build.

### 5.2 Required fields

In addition to the common envelope:

| Field | Requirement |
|---|---|
| `provider.id` | Provider ID from the unified spec |
| `provider.repo` / `role` / `required` | Declared identity and requirement |
| `provider.local_path` | Inspected path (not a deployment claim) |
| `inspected_source` | `worktree` or `origin/main` |
| `worktree_head` / `origin_main` | Exact commit identities when available |
| `dirty` / `behind_origin_main` | Local repository state |
| `artifacts[]` | Path, `present`, SHA-256, source |
| `contracts[]` | File, expected substring, `present`, source |
| `provider.status` | `available`, `unavailable`, or `drift` |
| `catalog_sha256` | Digest of the unified catalog |
| `kernel_catalog` | Count, source/fixture digests, local-only count, dispatch count |
| `spec_sha256` / `manifest_sha256` | Inputs used by the audit |
| `scan_repositories` | Whether local HEAD/dirty evidence was included |

### 5.3 Baseline result

At baseline, `tools/mth_unified.py --check` is green with:

- **127 catalogued kernels**;
- **94 unique sources** and **93 unique fixture files**;
- **5 native-dispatch ABI kernels**;
- **7 providers**, **3 required** (`nanrouter.control`, `nan0s.vm`,
  `hermes.runtime`) and **4 optional**;
- **7 available, 0 warnings** in the recorded audit;
- `claims_ci_verified=false` and `claims_live_deployment=false`.

The catalog digest recorded for the baseline is
`e6209216519fdc06fa52a9070cd7a819a1140165a3e954a4eeace4b808ab6115`.
The universe-map directory digest is
`9a836c5523b8fe356a14fb663eb7ffa5d08b7ee0975a01dd9844b59b07b389c4`.

A provider `available` result is contract-presence evidence only. It is not a
build result, a CI result, or a live deployment.

### 5.4 Promotion rules

1. `provider_contract` evidence may promote only the claim “the declared
   contract text is present in the inspected source.”
2. A required provider that is missing or drifted blocks the catalog in strict
   mode. In relaxed mode it is a warning, not green evidence for that provider.
3. Optional provider absence is a warning. It never becomes a green provider
   result by default.
4. Cross-repo runtime integration requires E2/E5 evidence from an executed
   integration path. Contract audit alone cannot promote it.
5. `origin/main` fallback is usable only when the remote ref was already
   fetched. The audit must record the remote commit; it must not infer that the
   remote ref is current.
6. A dirty worktree may be audited, but the result must be labeled as
   worktree-local and cannot be represented as canonical CI evidence.

### 5.5 Invalidation rules

A provider record becomes stale or invalid when:

- `spec/mth-unified-system.v1.json` changes a provider, artifact, or contract;
- a required artifact's digest changes;
- a contract substring disappears or moves to a different file;
- the provider `HEAD` or fetched `origin/main` moves;
- the inspected source switches between worktree and `origin/main`;
- a strict-mode required provider disappears;
- the unified catalog digest changes;
- the sibling repository's history is rewritten or force-pushed.

### 5.6 Forbidden E3 claims

- “The provider is live because its checkout exists.”
- “The contract string is present, so the interface is behaviorally compatible.”
- “All seven providers are green for deployment.” The audit is contract
  presence, not runtime status.
- “`nan0s.vm` is executing these kernels” merely because its source contract is
  present.
- “`NaNLM` is an MTH authority.” The spec explicitly classifies it as an
  experiment, never a production MTH authority.
- “`origin/main` content is the deployed build.”
- “The unified catalog is a cross-repo execution proof.”

## 6. E4 — Signed volume-registry evidence

### 6.1 What this class establishes

The volume-registry contract is defined by `spec/volume-registry.md`,
`spec/volume-registry.schema.json`, and `runner_riddle/volume_registry.py`. It
binds four canonical shard-zero tier identities to Koyeb provider volumes and
requires a generation-chained, HMAC-SHA256-authenticated document.

A valid E4 record establishes, at one generation and observation time:

- the registry schema and canonical tier identities are correct;
- the digest and HMAC authentication match the supplied key;
- generation and previous-digest chaining are valid;
- all four canonical shard-zero volumes are present;
- each volume is `health=green` and `mount_verified=true`.

It does not establish that the MTH service is live, that kernels execute, or
that an unsigned configuration is healthy.

### 6.2 Required fields

Top-level registry fields:

| Field | Requirement |
|---|---|
| `schema` | `nanrouter.volume-registry.v1` |
| `network_id` | Non-empty network identity |
| `generation` | Positive integer, monotonic |
| `previous_digest` | `null` for genesis, otherwise 64-hex SHA-256 |
| `volumes` | At least four entries; exactly one shard-0 entry per tier |
| `registry_digest` | SHA-256 of the canonical core |
| `signature` | HMAC-SHA256 over the canonical core; not a public-key signature |

Per-volume fields:

| Field | Requirement |
|---|---|
| `tier` | `BS0`, `MC0`, `SC0`, or `GM0` |
| `logical_address` | Stable canonical address for tier/shard; never a provider ID |
| `shard` | `0..255`; shard 0 required for every tier |
| `provider` | `koyeb` |
| `provider_volume_id` | Real provider ID; placeholders forbidden |
| `mount_root` | Normalized absolute physical mount path |
| `database_file` | Tier-matching database filename |
| `region` | Non-empty Koyeb region |
| `health` | `green`, `degraded`, `unavailable`, or `unknown` |
| `mount_verified` | Boolean |
| `observed_at_tick` | Non-negative observation tick |
| `generation` | Positive and no newer than the registry generation |

Verification envelope fields:

| Field | Requirement |
|---|---|
| `key_id` / key fingerprint | Identity of the trust root; never the key itself |
| `verifier` / version | Which implementation verified the payload |
| `verification_result` | Digest, generation, and pass/fail result |
| `observed_at` / `valid_until` | Observation window |
| `mount_observation_method` | How mount and database presence were checked |

### 6.3 Green definition

A volume registry is green only when **all** of the following hold:

1. Schema, digest, and HMAC authentication are valid.
2. Generation is positive and the previous-digest chain is valid.
3. Exactly one shard-0 volume exists for each of `BS0`, `MC0`, `SC0`, `GM0`.
4. Every shard-0 volume has `health=green` **and** `mount_verified=true`.
5. Logical addresses match tier/shard identity and CRC; provider IDs and mount
   roots are unique and real.
6. Observation age is within the configured policy.

A missing registry is `unknown`, not green. A present but unhealthy registry is
`degraded` or `unavailable`, not green. Configuration alone never produces green.

### 6.4 Baseline status: blocked, and no signature claim

At baseline, E4 is **blocked**:

- no production signed registry payload is present in the repository;
- no production HMAC key, key ID, or trust root is available;
- no real Koyeb provider volume IDs or mount observations are recorded;
- `spec/p13-gates.json` records `signed-volume-registry` as `blocked`.

The code, schema, and tests can exercise the verifier with synthetic material.
That is code-path coverage, not evidence that a production registry was signed
or verified. This document makes **no cryptographic signature verification
claim**. The registry's `signature` field is HMAC-SHA256, a symmetric
authentication tag, not a public-key signature.

### 6.5 Promotion rules

1. `unknown` may become `configured` only when a registry payload, key identity,
   trust root, and real provider bindings exist.
2. `configured` may become `green` only after the verifier passes and all four
   shard-0 volumes satisfy the green definition above.
3. A green registry promotes only the volume-binding claim at that generation
   and observation window. It does not promote a live service or MTH execution.
4. A registry signed with a test key, or generated from placeholder IDs, is
   test evidence, not production evidence.
5. A volume health claim must be derived from a mount observation plus the
   signed registry. It cannot be inferred from the presence of a mount path,
   a Koyeb dashboard, or a configuration file.

### 6.6 Invalidation rules

A registry record becomes stale or invalid when:

- the key is rotated without updating the trust root;
- `generation` regresses, forks, or `previous_digest` does not match;
- a provider ID, mount root, region, or database binding changes;
- a volume becomes `degraded`, `unavailable`, or `mount_verified=false`;
- a volume is detached or the observation becomes older than policy;
- the schema or canonical tier identity changes;
- duplicate addresses, provider IDs, or mounts appear;
- a placeholder provider ID is introduced;
- digest or HMAC authentication fails.

A newer generation supersedes an older one. The older record is retained for
history but is not current evidence.

### 6.7 Forbidden E4 claims

- “The volume registry is signed” without a payload, key identity, trust root,
  digest, generation, and verification result.
- “Cryptographic signature verification passed” for production material. No
  such verification is claimed here.
- “HMAC-SHA256 is a public-key signature.”
- “The schema or verifier code is a signed registry.”
- “The volumes are green because the configuration lists them.”
- “A logical NaN address is a Koyeb provider volume ID.”
- “A detached or unverified volume is green.”
- “A green volume registry proves MTH execution or service liveness.”

## 7. E5 — Live deployment evidence

### 7.1 Sub-scopes

Live evidence must name its sub-scope. The three sub-scopes are separate:

1. **Live service** — a specific deployed build serves the recorded endpoint and
   returns the expected health contract.
2. **Live MTH execution** — a recorded request traverses point 0, admission,
   lease/JAHS, and the native executor, and returns a recorded MTH result.
3. **Live volume binding** — the deployed service observes the signed registry
   generation and the four volume bindings at the recorded time.

A live service does not imply live MTH execution. A green volume registry does
not imply a live service. A deployment YAML does not imply any of them.

### 7.2 Required fields

In addition to the common envelope:

| Field | Requirement |
|---|---|
| `deployment.id` | Koyeb app/service/deployment identifiers |
| `deployment.region` | Deployment region |
| `source.repo` / `commit` | Source repository and exact commit |
| `image.digest` | Built image identity |
| `deployed_at` | Deployment timestamp |
| `endpoint` / DNS / TLS | Public or private endpoint and certificate state |
| `health.status` / body digest | Recorded `/healthz` response |
| `build_revision` | Must match the deployed commit/image |
| `runtime` | Word size, ring slots, active slots, guest configuration |
| `point0.transcript` | Exact request/response for the claimed path |
| `runner_ring` | Active slot, epoch, JAHS seal, freshness |
| `volume_registry` | Generation, digest, health; `unknown` if absent |
| `live_route_commit` | Must be `false`; the service does not commit routes |
| `mth_execution` | Packet/job/kernel/runner/lease/route/result evidence for live MTH |
| `logs` | Retained deployment and request logs |
| `operator` | Who performed/observed the deployment |
| `rollback` | Previous deployment identifier |
| `valid_until` | Liveness window; no open-ended live claim |

### 7.3 Promotion rules

1. A deployment definition, image build, or container smoke cannot promote a
   live-service claim. A live claim requires a deployment transcript with an ID,
   region, build revision, endpoint, and recorded health response.
2. A live-service claim requires the health response to match the exact build
   and address contract.
3. A live MTH claim requires a separate per-request transcript that includes the
   admission/lease/JAHS/route context and the native execution evidence. A
   health check is not an MTH execution.
4. A live volume-binding claim requires the signed registry generation and
   digest observed by the deployed service, not just a local registry file.
5. Staging, a local container, a tunnel, or a CI smoke is not production live
   evidence.
6. A live claim expires at `valid_until`. Continuous liveness requires a
   monitoring series covering the interval; a single point-in-time probe is not
   continuous evidence.

### 7.4 Baseline status: blocked

At baseline, E5 is **blocked**:

- `spec/p13-gates.json` records `live-koyeb-nannet0` as `blocked`;
- no live deployment identifier, region, build revision, endpoint transcript,
  point-0 transcript, ring/JAHS snapshot, or deployed health response is part of
  this evidence baseline;
- the Koyeb container smoke is CI readiness only. It builds the image, starts it
  without Koyeb credentials, and asserts the local `/healthz` contract,
  including `volume_registry={"health":"unknown","configured":false}` and
  `live_route_commit=false`. It passed in recorded run `42542521266`;
- `docs/KOYEB_CUTOVER_EVIDENCE.md` records a portal/ring cutover, not a live MTH
  execution or a signed volume-registry verification. It is out of scope for
  this model and is not promoted to MTH live evidence.

This document does **not** claim a live Koyeb deployment. Any statement that the
unified MTH system is live is a forbidden claim at this baseline.

### 7.5 Invalidation rules

A live record becomes stale or invalid when:

- a new deployment, revision, image, or source commit is rolled out;
- the endpoint, DNS, or TLS identity changes;
- `/healthz` is unreachable, non-200, or reports a different build revision;
- the runtime declaration or point-0 address changes;
- the runner ring has no active slot, a stale epoch, or an invalid JAHS seal;
- the signed registry generation/digest differs from the observed deployment;
- the `live_route_commit` value is anything other than `false`;
- the observation exceeds `valid_until` or the monitoring series has a gap;
- a rollback occurs;
- logs or the deployment transcript are unavailable.

### 7.6 Forbidden E5 claims

- “Koyeb is live” based on the container smoke, a Docker run, a deployment YAML,
  or a source checkout.
- “The unified MTH system is deployed” without a deployment ID and transcript.
- “The portal cutover is MTH live evidence.”
- “`/healthz` returning 200 proves MTH execution.”
- “A green volume registry proves a live service.”
- “The service commits routes.” `live_route_commit` is explicitly `false`.
- “Production MC0DB/BS0DB registration is complete” without volume and
  registration evidence.
- “CI green means production green.”

## 8. Artifact-to-evidence map

| Artifact | Evidence class | What it records | Required companion evidence | What it cannot establish |
|---|---|---|---|---|
| `spec/wave-capabilities.json` | E1 index; E2 declaration | 96 kernels, source/fixture paths, markers, steps, precision, workspace, status, `ci_verified` | Local runner records and canonical CI run IDs | CI by itself, numerical proof, deployment |
| `spec/universe-map.json` | E1-adjacent static map | 256 pages, 1,048,576 words, 32,896 relation points, deterministic page-directory digest | Generated-map check and native universe-map fixture | Mathematical truth, authorization, execution |
| `spec/mth-unified-system.v1.json` | E3 policy | Provider roles, required artifacts, contract strings, authority boundaries, evidence policy | `tools/mth_unified.py` audit output and provider HEAD/`origin/main` records | Provider availability, CI, live service |
| `tools/run_mth_fixtures.py` | E1 producer | 94 fixture entries, exact assemble/execute/marker workflow | Source/fixture/toolchain digests, logs, observed steps | CI status, live status, independent oracle |
| `tools/audit_nan_native.py` | Static coverage / boundary evidence | Source registration, fixture wiring, runner/CI references, host-import boundary | Green audit output and repository commit | Numerical equivalence, CI execution, deployment |
| `tools/mth_unified.py` | E3 producer | Kernel catalog, source/fixture SHA-256, provider contract audit, `claims_* = false` | Exact provider commits, spec/manifest digests, audit output | CI, provider runtime, live deployment |
| `.github/workflows/koyeb-container-smoke.yml` | E2 readiness | Credential-free container build and local `/healthz` contract | Canonical run ID and commit | Live Koyeb deployment, mounted volumes, MTH execution |
| `spec/volume-registry.schema.json` + `spec/volume-registry.md` | E4 contract | Registry fields, tier identities, HMAC/generation rules, green definition | Production payload, key identity/trust root, mount observations | That a production registry exists or was verified |
| `runner_riddle/volume_registry.py` + `runner_riddle/live_preflight.py` | E4 verifier | Read-only digest/HMAC/generation/health checks | Production registry and key material | Production verification by themselves |
| `.github/workflows/mth-*.yml` | E2 producer | Native fixture, manifest, and unified-audit runs | Run ID, exact commit, job log | Live deployment |
| `docs/R10_IMPLEMENTATION_EVIDENCE.md` | Evidence index | Recorded local step counts, local suite result, CI run IDs | The original logs/artifacts when available | Fresh re-execution |

The baseline static audit is green over 96 kernels, 94 native sources, 93 unique
manifest fixtures, and 94 runner entries. That audit is valuable precisely
because it checks coverage and boundaries; it is not a numerical oracle.

## 9. Promotion rules at a glance

| Promotion | From | To | Required evidence | Authority | Cannot skip |
|---|---|---|---|---|---|
| Kernel source exists | absent | `source_written` | Source + fixture registered; manifest entry; audit coverage | NaNROUTER catalog owner | Source presence alone |
| Local native pass | `source_written` | `native_verified` | E1 record: exact digests, marker, steps, toolchain, clean commit | Canonical runner operator | CI, live, provider audit |
| Canonical CI pass | `native_verified` | `ci_verified=true` | E2 record: canonical run ID, commit, job, success, logs | Canonical GitHub Actions | Local pass, manifest edit |
| Provider contract present | unknown | `available` | E3 record: artifact paths, contract substrings, inspected source, digests | `tools/mth_unified.py` | Build, CI, live |
| Volume registry valid | unknown/configured | `green` (E4) | Signed payload, key identity/trust root, generation chain, four green+mounted volumes | Registry verifier + operator | Configuration alone, CI, live |
| Service live | deployment definition | live service (E5) | Deployment ID, region, build revision, endpoint, health transcript | Deployment operator | CI, smoke, source presence |
| MTH live | live service | live MTH execution (E5) | Per-request point-0/admission/lease/JAHS/route/native result evidence | Deployment operator + evidence record | Health check alone |
| Volume binding live | E4 green | live volume binding (E5) | Deployed service observes registry generation/digest and mount state | Deployment operator | Local registry file alone |

**No transitive promotion.** Each row is class-local. A provider `available`
does not imply a build; a build does not imply CI; CI does not imply a volume
registry; a volume registry does not imply a live service; a live service does
not imply live MTH execution.

## 10. Invalidation rules at a glance

| Trigger | Invalidates | Required action |
|---|---|---|
| Source or fixture content changes | E1 subject, E2 subject, catalog digest | Re-run local fixture; re-run canonical CI; regenerate catalog |
| Manifest entry/version/status changes | E1 index, E2 promotion, catalog | Re-audit coverage; re-establish CI for changed subject |
| Runner, assembler, VM, or toolchain changes | All E1 records | Re-run the affected local fixture set |
| Workflow or pinned toolchain changes | E2 records | Re-run canonical workflows on the exact commit |
| New commit/merge | Promotion eligibility for old commit | Re-baseline; old records remain historical |
| Provider HEAD or `origin/main` moves | E3 record freshness | Re-run unified audit; record new source commit |
| Contract string or required artifact changes | E3 provider status | Re-audit; mark drift/unavailable as appropriate |
| Key rotation without trust-root update | E4 authentication | Update trust root and re-verify; do not reuse old green |
| Registry generation regression/chain break | E4 | Reject; investigate fork/rollback; never promote |
| Volume health/mount/observation changes | E4 green | Re-observe; degrade or block as required |
| Deployment revision/DNS/TLS changes | E5 live record | New deployment transcript; old record expires |
| Ring/JAHS/registry mismatch | E5 live MTH/volume claim | Block; do not infer live from stale state |
| Observation window expires | E5, and E4 where age-bounded | Re-observe or report stale/unknown |
| Dirty/untracked worktree at promotion | All tracked claims | Commit the exact artifacts or keep the result local-only |
| Logs/artifacts expire | E2/E5 verifiability | Mark `recorded-unverified`; cannot be reused for new promotion |

Records are append-only. Invalidation changes the current status of a record; it
does not silently delete or rewrite history.

## 11. Consolidated forbidden claims

The following are forbidden regardless of which artifact appears to support
them:

1. “The unified MTH system is live on Koyeb.” There is no E5 record at this
   baseline.
2. “The volume registry signature was cryptographically verified.” There is no
   production payload/key/trust-root record, and this document makes no such
   claim.
3. “A production signed volume registry exists.” Only the contract, schema,
   verifier, and test paths exist.
4. “Live MTH execution is proven.” No live request/native-result transcript
   exists.
5. “Production MC0DB/BS0DB registration is complete.” No deployed volumes or
   registration evidence exists.
6. “The Koyeb smoke is a deployment.” It is a credential-free CI readiness
   check.
7. “Local native PASS is CI-verified.” E1 and E2 are separate.
8. “CI is live.” E2 and E5 are separate.
9. “A provider checkout is a deployed provider.” E3 is contract presence.
10. “A contract substring is behavioral compatibility.” It is only text
    presence.
11. “96 catalogued kernels means 96 fixtures were executed.” The baseline has 94
    runner entries and 93 unique manifest fixture files.
12. “94 runner fixtures means 94 catalogued kernels.” The runner has one
    runner-only dispatch fixture and some kernels share fixtures.
13. “1,452+ local tests prove native numerical correctness.” They are host and
    control-plane tests plus fixture-oriented coverage, not an independent
    numerical oracle.
14. “The manifest's `ci_verified=true` is self-authenticating.” It is a ledger
    field backed by E2 run records.
15. “The universe map proves mathematical truth.” It is an address/coverage map;
    the catalog explicitly records `claims_relations_true=false`.
16. “A graph claim probe or path witness is an authorized numerical MTH proof.”
    The claim probe is a bounded candidate query; the path witness is excluded
    and separately gated.
17. “A route or address mapping authorizes execution or merge.” Address
    resolution is not truth, authorization, or a native head-bank update.
18. “The service commits routes.” `live_route_commit` is `false`.
19. “HMAC-SHA256 is a public-key signature.” It is symmetric authentication.
20. “A green volume registry proves the service is live.” E4 and E5 are
    separate.

## 12. Current green evidence vs blocked external gates

**Baseline:** commit `12980a3`. “Green” in this table means green only for the
named evidence class and scope. It does not promote any other row.

| Status | Gate | Class | Baseline result | Exact scope / limitation |
|---|---|---|---|---|
| GREEN | Kernel catalog coverage | E1 index / static | 96 kernels, 96 declared `ci_verified`, 94 sources, 93 fixture files, 94 runner entries | Coverage and ledger only; not execution of all 96 |
| GREEN | Static NaN-native boundary | Static audit | `status=green`; 96 kernels; 94 sources; 93 fixtures; 94 runner fixtures; no forbidden production imports | Static coverage/import audit, not numerical equivalence |
| GREEN | Local native fixture runner | E1 | 94/94 PASS recorded against NaN0S `f31143e`; pinned canonical `fe63617` differs only in a CI workflow per the recorded note | Local only; exact toolchain; not a fresh CI run |
| GREEN | Host universe map | Static/generated | 256 pages, 1,048,576 words, 32,896 relation points, coverage 1.0; generated-map check passes | Address coverage only |
| GREEN | Native universe-map fixture | E1 + E2 | PASS, 12,916,386 steps; recorded CI run `42539617226` | One fixture; no relation-truth claim |
| GREEN | Local Python suite | Local tests | 1,452+ tests; baseline record `Ran 1452`, `OK (skipped=30)` | Host/control suite; not native numerical proof |
| GREEN | Canonical native CI | E2 | 96/96 declared CI-verified; recorded runs `42405649076`, `42539617226`, `42539739728`, `42542521347`, `42542521393` | Historical records; exact commits/workflows; not re-run here |
| GREEN | Unified catalog and provider contracts | E3 | 96 kernels, 5 dispatch ABI, 7/7 providers available, 0 warnings; `claims_ci_verified=false`, `claims_live_deployment=false` | Contract presence only; no provider runtime claim |
| GREEN | Unified audit workflow | E2 | Recorded run `42542831186` | Universe-map check, catalog check, two test modules; no native fixture execution |
| GREEN | Koyeb container smoke | E2 readiness | Recorded run `42542521266`; health contract passes; volume registry unknown/configured false; `live_route_commit=false` | Container readiness only; no Koyeb credentials, no live service |
| BLOCKED | Signed volume registry | E4 | No production payload, key identity, trust root, provider IDs, or mount observations; P13 gate blocked | No volume green; no signature claim |
| BLOCKED | Live Koyeb/NANNET0 MTH deployment | E5 | No deployment ID, region, build revision, health/point-0 transcript, ring/JAHS snapshot; P13 gate blocked | No live deployment claim |
| BLOCKED | Production MC0DB/BS0DB registration | E5/E4 | No mounted production volumes or registration/backup evidence | No production registration claim |
| BLOCKED | Live native numeric executor | E5 | No deployed executor, admission receipt, numeric result, or deterministic replay evidence | No live MTH execution claim |
| BLOCKED | Cross-repo runtime integration | E3 + E2/E5 | Provider contracts are present, but no two-repo execution or deployed integration transcript | No runtime or deployment claim |

The blocked rows are external gates, not paperwork gaps that can be closed by
editing this document. They require real deployment, registry, volume, or
cross-repo execution evidence.

## 13. Re-baselining checklist

Before reusing this model after the baseline commit changes:

1. Record the new commit SHA and tree SHA.
2. Recompute the kernel, source, fixture, runner, and test counts from tracked
   files.
3. Re-run `tools/gen_universe_map.py --check`.
4. Re-run `tools/audit_nan_native.py`.
5. Re-run `tools/mth_unified.py --check` (and `--scan-repositories` only when
   local repository state is part of the intended record).
6. Re-run the affected local fixtures and canonical CI workflows.
7. Re-check provider `HEAD`/`origin/main` and contract digests.
8. Re-check any signed volume registry generation, observation age, and trust
   root.
9. Re-check the deployment ID, build revision, endpoint, health transcript, and
   `live_route_commit=false`.
10. Update the evidence table and mark superseded records; never silently
    convert a blocked gate to green.

Until that checklist is completed, the counts and statuses in this document are
valid only for commit `12980a3`.
