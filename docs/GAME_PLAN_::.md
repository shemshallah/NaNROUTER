# GAME PLAN `::` — NaN Mathematical Linker, Validity, and Self-Organizing Memory

**Status:** architecture and integration plan; P0–P12 control-plane integration is implemented and tested, while P13 live/experiment gates remain explicitly blocked. The evidence ledger is authoritative for counts and CI IDs.
**Date:** 2026-11-07.
**Parent plans:** `docs/game_plan_deep.md`, `docs/game_plan_foundations.md`, `docs/GAME_PLAN_MTH.md`, `docs/DEEP_PLAN_CONT.md`.
**Evidence ledger:** `docs/R10_IMPLEMENTATION_EVIDENCE.md`.
**Implementation queue:** `docs/IMPLEMENTATION_TODO.md` (the `::` queue at the top).
**Canonical language:** NaN16.
**Canonical math owner:** native MTH kernels in the one NaNLMind universe.
**Canonical routing owner:** NaNROUTER through stable point 0.
**Guest-budget update:** GLT is now **2 MiB and adjustable for guest words**. The checked-in `main` now defaults to **2 MiB / 262,144 words / 64 pages**, with 1 MiB and 512 KiB compatibility modes. GLT-enforced page-limit loading remains a separate gate.

This document does not create a second universe, a second runner ring, a second store, or a second mathematical authority. It defines how the five proposed systems fit into the existing MTH/NaNROUTER control plane without collapsing their responsibilities.

### Contents

- 0 — Reading discipline and non-claims
- 1 — Executive synthesis
- 2 — Current baseline and 2 MiB update
- 3 — Authority separation
- 4 — Namespace and identity
- 5 — The universal mathematical leaf
- 6 — Function, rule, and relation registry
- 7 — The `::` linker
- 8 — Mathematical validity engine
- 9 — NMP protocol
- 10 — NaNNet meta-mapping and storage
- 11 — Execution ring, 255 logical lanes, capabilities
- 12 — Null, void, undefined, absence
- 13 — Learning, rule discovery, proof status
- 14 — Scratch, oscillation, pruning, retention
- 15 — Security and bounds
- 16 — 2 MiB integration
- 17 — End-to-end v1 demonstration
- 18 — Integration map and current code gaps
- 19 — Phased priorities P0–P13
- 20 — Ordered TODO and verification backlog (T01–T20 + X/B/P0 tests)
- 21 — Risks, contradictions, decisions
- 22 — Final architecture
- Appendices A–C — schemas and first milestone

---

## 0. Reading discipline and non-claims

Every statement below belongs to one of these classes:

| Class | Meaning |
|---|---|
| **Established** | Follows from definitions or the existing repository contract. |
| **Implemented** | Backed by a native fixture, Python test, or CI run in this repository. |
| **Target** | The implementation contract this plan asks for. |
| **Hypothesis** | Plausible, measurable, not yet established. |
| **Open** | Requires a decision, proof, or experiment. |
| **Rejected** | Contradicted by evidence or by the architecture's own rules. |

A passing kernel fixture is not a proof of general mathematical correctness. A learned association is not a rule. A typed preflight success is not proof that a numerical result is accurate. A `NULL` is not a zero. A committed leaf is not automatically a promoted rule.

The plan also preserves the existing distinction:

> **The linker explores. The validity engine authorizes. Capability determines whether a runner can execute. The scheduler decides where. The runner executes. The store and evidence plane remember.**

No one of those is allowed to silently become another.

---

## 1. Executive synthesis

NaNLMind is best understood as a **mathematical operating environment**, not a calculator, a graph database, or a pile of embeddings. Its central cycle is:

```
observe a mathematical object or relationship
        -> resolve identities and versions
        -> classify types, domains, dimensions, and existing relations
        -> propose candidate transformations through `::`
        -> preflight each candidate against the authoritative rule snapshot
        -> select one or more candidates for a bounded objective
        -> issue NMP work to the execution ring
        -> execute native NaN16 primitives
        -> commit immutable result leaves with provenance
        -> feed selected results back into future conjunctions
```

The five cooperating systems are:

1. **NaN Mathematical Address Space** — stable identities for leaves, functions, rules, relations, scratch objects, null/void objects, and metadata.
2. **`::` Mathematical Linker** — an exploratory candidate generator. It is not an operator that silently adds, multiplies, or authorizes anything.
3. **Mathematical Validity Engine** — the sole authority on whether a proposed transformation is permitted. It sits on the execution authorization path, not beside it.
4. **NaNNet Meta-Mapping** — the authoritative directory of what exists, what it means, where it lives, how it is versioned, and how it is routed.
5. **NaNLMind Execution and Learning Heads** — bounded exploration, calculation, evaluation, memory, pruning, and rule proposals.

A cross-cutting sixth concern, already present in the repository, is the **evidence/promotion plane**: BS0DB traces, MC0DB registries, leases, capabilities, seals, signatures, and CI evidence. It is not a sixth math authority.

The strongest architectural rule is:

> **The mind may propose any mathematically expressible conjunction. It may not execute a transformation that lacks a current, digest-bound preflight authorization and a capability match. No shortcut, scratch lane, learning head, or remote worker may bypass that gate.**

The second strongest rule is:

> **Mathematical truth is not learned utility, and learned utility is not mathematical truth.** Retention, ranking, novelty, and task benefit may decide what to cache or explore; they may never redefine validity.

---

## 2. Current baseline and the 2 MiB update

### 2.1 What exists

At the time of writing the checked-in `main` contains:

- **63 native MTH kernels** with fixtures; 60 local and 61 total fixtures;
- **58 locally runnable fixtures** and **59 total fixtures**, including the K256 pair fixture that is CI-only locally;
- canonical CI run `42396090387` (and later docs-only runs) passing **121 workflow steps**;
- **653 Python tests** (1 skipped) after the P7–P12 math integration additions;
- **2 MiB adjustable guest budget** (`runner_riddle/budget.py`; 262,144 words / 64 pages), with 1 MiB legacy profiles;
- `MthRegistry`/`MthPlan`, `MthSystem`, `WaveStore`, `WaveService`, `WaveRingScheduler`, point-0 bridge/router, point-0 HTTP, tile orchestrator, file-backed pair pages, page-backed pair executor, live preflight, LM ablation harness, R7 harness, and JAHS handoff seal.

Existing MTH kernels are the **implementation layer**. They are not yet a full mathematical registry: the current `MthKernelDescriptor` has no semantic input/output signature, domain, precondition, postcondition, undefinedness policy, or proof status. That is the gap this plan fills.

### 2.2 The 2 MiB guest target

The guest limit is now **2 MiB and adjustable for guest words**. The integration target and checked-in default are:

```
2 MiB = 2,097,152 bytes
      = 262,144 NaN16 words (8 bytes per word)
      = 64 pages of 32 KiB
```

A 1 MiB compatibility mode remains selectable:

```
1 MiB = 131,072 words = 32 pages of 32 KiB
```

The 2 MiB integration is checked in at `MthSystem`, point-0 framing, registration, live preflight, tile orchestration, and the page-backed pair executor. The default remains adjustable; 1 MiB and 512 KiB compatibility modes are explicit tests and must not silently admit 2 MiB-only plans.

| Object | 2 MiB fit | Notes |
|---|---:|---|
| 256×256 matrix (65,536 words) | yes, 512 KiB | one matrix plus plenty of scratch |
| 256×256 matrix + eigenvectors (131,072 words) | yes, 1 MiB | 1 MiB remains for code/scratch |
| 256×256 complex float32 (two 65,536-word planes) | yes, 1 MiB | 1 MiB remains |
| full 256 pair `U + L + output` (196,608 words) | yes, 1.5 MiB | code/vectors must fit in ~64K words |
| full-U 16×16 pair-tile reference (73,990 words) | yes | comfortably |
| 512×512 dense matrix (262,144 words) | exactly 2 MiB | no code/scratch room; not a general target |
| `65,536 × 65,536` dense product | **no** | 4.29B entries; 16 GiB at 4-byte payloads, 32 GiB at 8-byte NaN words |

The 8 MiB universe remains 256 pages of 32 KiB: 255 head pages plus one NANNET0 page. The 2 MiB guest holds 64 of those pages, not 16 or 32.

The 2 MiB target changes what is *feasible*; it does not change the rule that the 7 GiB active-runner ceiling is for versioned pages, caches, checkpoints, and experiment corpora, not six simultaneous runners and not a dense 65,536² operator.

### 2.3 Memory policy

- Default target: **2 MiB**, checked in and test-covered.
- Caller override: `guest_words`/`guest_bytes`, bounded by the declared platform ceiling.
- Compatibility: 1 MiB and 512 KiB test modes continue to work.
- Point-0 hard frame ceiling: 262,144 words at 2 MiB; a smaller per-frame limit remains allowed.
- Health must expose `guest_budget_words`, `guest_budget_bytes`, `page_bytes`, and `guest_budget_pages`.
- A plan that needs more than the effective budget is rejected before it reaches the store, service, or executor.
- The 2 MiB target is a policy/configuration fact, not proof that GLT enforces it. The GLT gate remains explicit.

### 2.4 What 2 MiB does *not* authorize

- It does not authorize arbitrary dense symbolic expansion.
- It does not authorize a 65,536×65,536 operator.
- It does not authorize storing a full hypergraph in one flat guest buffer.
- It does not remove the need for page windows, low-rank representations, or evidence.
- It does not make a mathematical claim valid. Memory capacity is not validity.

---

## 3. Authority separation

The system must distinguish seven different questions:

| Question | Authority | Failure state |
|---|---|---|
| What object is this? | address space + meta-mapping | unknown reference |
| Is the operation mathematically defined for these types/domains? | validity engine, rule level 0–3 | `INVALID` / `UNDEFINED` |
| Is it numerically defined for these values? | native precondition/certificate kernel | `UNDEFINED` or `UNKNOWN` |
| Is it authorized for this universe/ACL? | authorization gate | `UNAUTHORIZED` |
| Can this runner implement it now? | capability registry | `UNAVAILABLE` / `UNSUPPORTED` |
| Where and when should it run? | scheduler | `QUEUED` / `CANCELLED` |
| Did the implementation execute successfully? | executor/evidence plane | `FAILED` |

These must never collapse into one `NULL`.

### 3.1 The four-way separation

1. **Mathematical correctness** is a property of a typed operation under a declared domain and rule set.
2. **Validity** is the authoritative preflight decision for a specific leaf versions/rule snapshot.
3. **Authorization** is a policy decision about whether this universe/head/principal may request the operation.
4. **Capability/availability** is a deployment fact about which runner/implementation can execute it.

A capability mismatch is not mathematical null. An authorization failure is not undefinedness. A stale ruleset is not a failed proof.

### 3.2 No alternate execution path

The validity engine must be on the **only** path from a selected candidate to a runner:

```
candidate
  -> NMP packet
  -> preflight digest
  -> MthSystem / WaveService admission
  -> lease with matching preflight/ruleset snapshot
  -> native execution
  -> evidence
```

The following are forbidden:

- a scratch head directly invoking an executor;
- a learning head mutating a mapping and then executing under the old preflight;
- a remote worker accepting a packet without a matching preflight digest;
- a scheduler accepting a plan whose kernel is not native/CI verified;
- a `::` candidate marked "experimental" but executed as if level 0.

### 3.3 Truth, validity, proof, and lifecycle are orthogonal

Do not use one `status` field for seven different ideas. The minimum orthogonal record model is:

| Axis | Question | Example values | Writer |
|---|---|---|---|
| truth | Is the proposition true in the named theory/assumptions? | `definitional`, `theorem`, `refuted`, `open`, `unknown` | proof/refutation authority |
| validity | Is this representation licensed for use? | `V0` stored, `V1` admissible, `V2` bounded-validated, `V3` proof-checked | validity engine |
| proof | What is the state of the proof object? | `none`, `sketch`, `candidate`, `checked`, `refuted`, `stale`, `quarantined` | proof checker/registry |
| authorization | May this principal do this now? | `allow`/`deny` + scope | ACL/WaveService |
| capability | Can this runner execute this implementation? | `unavailable`, `declared`, `native_verified`, `degraded`, `revoked` | capability registry |
| utility | Does it help on measured tasks? | score + CI + scope + cost | experiment service |
| lifecycle | Is it proposed, active, deprecated, revoked? | `proposed`, `validated`, `committed`, `active`, `deprecated`, `revoked`, `archived` | lifecycle service |

Non-implications:

- authorized does not imply valid;
- valid does not imply true (V3 is relative to a theory/checker);
- capable does not imply correct;
- useful does not imply true or valid;
- active does not imply true;
- deprecated does not imply false;
- stale does not imply false;
- proof-checked does not imply true if the theory is inconsistent;
- `supported`/`ablation_passed` is an experiment outcome, not validity or proof.

Validity levels:

| Level | Earned by | Use |
|---|---|---|
| **V0** | schema parses, digest/provenance present | scratch/index only |
| **V1** | type/domain/symbol/side-condition checks | review, test planning |
| **V2** | V1 + deterministic bounded tests/exhaustive finite check/declared held-out protocol | heuristic/bounded use, explicitly envelope-bound |
| **V3** | V1 + proof object accepted by trusted checker against named theory, dependencies current | trusted derivation within that scope |

Rule authority levels and validity levels are different axes. A level-2 derived rule can be V2 or V3; a level-3 experimental rule is normally V0/V1 only. Until a trusted proof checker exists, cap production validity at V2 and label proof candidates unchecked. A host-language proof checker cannot establish MTH truth unless the checker itself is trusted/verified.

### 3.4 Authority table

| Layer | May propose | May validate | May authorize | May execute | May persist |
|---|---:|---:|---:|---:|---:|
| `::` linker | yes | no | no | no | no |
| validity engine | no | yes | no | no | evidence only |
| ACL/authorization | no | no | yes | no | policy evidence |
| capability registry | declarations | no | no | no | capability rows |
| scheduler/NMP runtime | no | no | no | dispatch only | job/lease evidence |
| native runner | no | native preconditions | no | yes | result evidence |
| learning head | rules/candidates | no | no | no | proposals/scratch |
| meta-mapping | no | no | no | no | identities/routes/versions |
| store | no | no | no | no | durable payloads/evidence |

---

## 4. Namespace and identity

### 4.1 Do not overload `HW0:123`

The existing address grammar uses `HW0:123` for a **head** in a hierarchy. A mathematical leaf is not a head, a node point, a runner slot, or a register offset. The examples in the design brief use `HW0:123` as a leaf display name; that is acceptable only as an alias bound by metadata.

Canonical mathematical references should use a separate scheme, for example:

```text
math://GM0:SC0:MC0:BS0:0/leaf/<opaque-leaf-id>@v<version>
math://GM0:SC0:MC0:BS0:0/function/<opaque-function-id>@v<version>
math://GM0:SC0:MC0:BS0:0/rule/<opaque-rule-id>@v<version>
```

The exact URI spelling is a versioned contract. The important points are:

- leaf identity is not a network point;
- leaf identity is not a local head index;
- leaf identity is not a content hash;
- the printable name is not the only identity;
- `HW0:123` remains a route/head reference unless an explicit alias record says otherwise.

### 4.2 `::` collision with the address grammar

The address grammar already uses `::` as a **traversal boundary** in `nan://` URIs. The mathematical linker uses `::` as a **conjunction proposal** between mathematical leaves. These are different languages.

Resolution:

- `nan://...` remains the routing grammar; its `::` never becomes a mathematical operation.
- `math://...` and NMP expressions are the linker language.
- A linker API accepts `MathRef`/leaf identities, not bare route strings.
- A raw `A :: B` text is accepted only by an explicitly invoked math-expression parser or a `/v1/math/link` endpoint.
- If a client sends a `nan://` route into the linker, the linker rejects it with `address_context_mismatch`.
- If a client sends a `math://` expression into the route resolver, the router rejects it with `route_context_mismatch`.

This prevents a future bug where a route traversal is silently executed as a dot product.

### 4.3 Identity levels

| Identity | Meaning | Mutability |
|---|---|---|
| `leaf_id` | stable identity of a committed mathematical object/history | immutable |
| `version` | monotonic version of a leaf's contents/mapping | new version, old retained |
| `content_digest` | digest of canonical mathematical contents | immutable for a version |
| `storage_ref` | physical location in BS0DB/pages/cache | mutable metadata, versioned |
| `function_id` | stable semantic function identity | versioned contract |
| `rule_id` | stable rule identity | versioned contract |
| `relation_id` | stable hyperedge/relation identity | immutable payload, versioned mapping |

Two leaves can share a content digest but have different leaf IDs, parents, provenance, permissions, or semantic roles. Identical content does not imply identical history.

### 4.4 Address regions

Logical classes, not yet hard-coded bit ranges (the finalized NaN encoding is authoritative):

| Region | Purpose |
|---|---|
| `M0` object leaves | vectors, matrices, scalars, tensors, geometric objects |
| `M1` function leaves | semantic operations and implementation bindings |
| `M2` relation leaves | hyperedges, graph relations, mappings |
| `M3` rule/validity leaves | signatures, contracts, certificates, proof status |
| `M4` scratch/candidate | speculative work, never authoritative |
| `M5` null/void/undefined | typed absence/undefined markers |
| `M6` meta-mapping | identity, routing, version tables, storage refs |

The allocator must reserve regions only after the NaN bit layout is frozen. Mirror pairs, palindromic addresses, BSR control heads, and NANNET node identities are not consumed by this allocation.

### 4.4a The 65,536-cell space is fully allocated

NaNLMind already accounts for every 16-bit cell address:

```
65,536 addresses = 256 palindromic head addresses + 32,640 mirror pairs
canonical classes = 32,640 non-palindromic pairs + 256 fixed points
```

There is no free cell address. A mathematical object therefore needs a **typed math-object address (MOA)** outside the cell space, not a new cell allocation. A cell-backed leaf may bind to one canonical non-palindromic pair index `π(a,b)` where `a < b`; it must never bind a palindromic address `a = b`, never allocate both orientations, and never consume the four palindromic NaN class nibbles. The pair index is a dense 0..32,639 namespace; the mirror orientation is an alias with its own address-register ACL, not a second object.

Recommended logical MOA: `kind + ordinal`, with kinds for leaf, function, rule, relation, scratch, void, and meta. Only `leaf` can optionally bind a cell; functions/rules/relations/scratch/void/meta do not need cell classes. This preserves the 256 heads, the mirror algebra, and the 8 MiB universe. The exact bit encoding must be frozen in a spec before implementation.

### 4.5 Canonical serialization and hashing

Version 1 should use **SHA-256** for compatibility with the existing 64-hex digest contracts (`wave_store`, `MthRegistry`, point-0, volume registry). BLAKE3 can be introduced later as an algorithm-tagged digest, but it must not silently change existing evidence verification.

Canonical serialization requirements:

- deterministic field ordering;
- explicit schema/version;
- no locale-dependent formatting;
- exact integer/float bit encoding;
- declared precision and endianness;
- no optional field omission that changes meaning;
- digest covers the canonical content, type, precision, numerical policy, and parents;
- a human-readable hash is an index/alias, never the sole identity.

---

## 5. The universal mathematical leaf

### 5.1 Definition

A leaf is a **typed mathematical packet**. It can represent a value, a function, a relation, a rule, a result, a null/void state, or a reference to a structured object. It is not necessarily a vector or a word.

Minimum fields:

```json
{
  "schema": "nanrouter.math-leaf.v1",
  "leaf_id": "nml:U0:vector:123",
  "version": 1,
  "kind": "vector",
  "type": {
    "name": "vector",
    "domain": "real",
    "shape": [128],
    "precision": "float32",
    "encoding": "NaN16-float32"
  },
  "content": {
    "digest": "sha256:...",
    "word_count": 128,
    "storage": "BS0DB",
    "payload_ref": "sha256:..."
  },
  "parents": [
    {"leaf_id": "nml:U0:vector:123", "version": 1, "role": "left"},
    {"leaf_id": "nml:U0:vector:234", "version": 1, "role": "right"}
  ],
  "operation": {
    "function_id": "math.vector.dot.v1",
    "function_version": 1,
    "ruleset_id": "math.rules.core.v1",
    "ruleset_version": 1
  },
  "status": "committed",
  "provenance": {
    "producer": "MC0:0/R0",
    "job_id": "...",
    "nanclock_tick": 0,
    "signature": "..."
  },
  "metadata_version": 1
}
```

A function leaf carries a semantic contract and one or more implementation bindings. A rule leaf carries a versioned contract and proof status. A result leaf carries parents and the exact function/rule snapshot. A null leaf carries a failure class and parents.

### 5.2 Leaf kinds

| Kind | Examples | May be executable? |
|---|---|---|
| `scalar` | real/integer/Boolean/extended scalar | no, value only |
| `vector` | 128/256-dimensional vector | no, value only |
| `matrix` | 128×128/256×256/255×255 | no, value only |
| `tensor` | tensor block | no, value only |
| `function` | semantic operation + implementation bindings | via registry only |
| `relation` | hyperedge, mapping, membership | via registered relation ops |
| `rule` | signature, precondition, proof/certificate | via validity engine |
| `result` | derived leaf with parents | may be fed back |
| `null` | typed no-result/failure | no |
| `void` | no object exists | no |
| `undefined` | mathematically undefined for these inputs | no |
| `unknown` | not yet established | no |
| `error` | execution/implementation failure | no |
| `hypergraph` | structured relation collection | via relation ops |

### 5.3 Immutability and versioning

- Committed mathematical contents are immutable.
- A transformation creates a new leaf/version; it does not overwrite the old content.
- Metadata mappings may change, but every change is versioned.
- The current mapping points to the current version; old versions remain recoverable.
- An evicted cache entry never deletes the durable leaf.
- A scratch leaf is explicitly marked non-authoritative and cannot be promoted without a new commit/preflight.

### 5.4 Provenance

Every committed result records:

- input leaf IDs, versions, and content digests;
- function/rule IDs and versions;
- candidate/linker ID and preflight digest;
- runner slot, epoch, job ID, lease token/digest;
- native source/fixture digest;
- numerical policy and reduction order;
- output digest;
- JAHS handoff seal for the execution step;
- signature where the deployment requires one.

A result without provenance is not a reusable mathematical leaf. It is at best scratch evidence.

### 5.5 Null/void/undefined leaves

They are typed objects, not numeric values:

| State | Meaning | Not |
|---|---|---|
| `ZERO` | valid numerical zero | not absence |
| `NULL` | no valid result was produced | not zero |
| `VOID` | no object/content exists | not undefined |
| `EMPTY` | valid empty structure | not null |
| `UNDEFINED` | operation has no defined result for inputs | not execution failure |
| `INFINITY` | valid extended value where domain permits | not overflow |
| `UNKNOWN` | not yet established | not false |
| `ERROR` | implementation/execution failure | not math undefined |

A null leaf must carry `failure_class`, `reason`, parents, linker ID, rule snapshot, and candidate count. A void input to a potentially valid operation may return `UNKNOWN`; a missing required reference returns a reference error; a zero divisor returns `UNDEFINED` if the function contract says so.

---

## 6. Function, rule, and relation registry

### 6.1 Function is a semantic contract, not a kernel

A function has a stable semantic identity:

```json
{
  "schema": "nanrouter.math-function.v1",
  "function_id": "math.vector.dot.v1",
  "version": 1,
  "family": "vector",
  "signature": {
    "inputs": [
      {"name": "a", "type": "vector", "domain": "real", "shape": [128]},
      {"name": "b", "type": "vector", "domain": "real", "shape": [128]}
    ],
    "output": {"type": "scalar", "domain": "real", "precision": "float32"}
  },
  "preconditions": [
    "shape(a) == shape(b)",
    "domain(a) compatible domain(b)"
  ],
  "postconditions": [
    "result == sum_i a[i]*b[i] under the declared numerical policy"
  ],
  "undefined_conditions": [
    "incompatible domains",
    "dimension mismatch"
  ],
  "numerical_policy": {
    "precision": "float32",
    "rounding": "round-to-nearest-even",
    "reduction_order": "increasing-index",
    "fma": false,
    "nan_propagation": "declared"
  },
  "implementations": [
    {
      "kernel_id": "mth.vector.dot256.f32",
      "version": 1,
      "source_digest": "...",
      "fixture_digest": "...",
      "capability_class": "vector.dot"
    }
  ],
  "proof_status": "verified",
  "status": "active",
  "contract_digest": "sha256:..."
}
```

The function identity is not the kernel identity. One function can have symbolic, CPU, parallel, or distributed implementations; all must satisfy the same contract. The linker selects a function; the scheduler selects an implementation/capability.

### 6.2 Existing `MthRegistry` compatibility

Do not overload `MthKernelDescriptor` with all semantic fields in one step. The clean migration is:

1. `MthRegistry` remains the validated implementation registry over `spec/wave-capabilities.json`.
2. A new `MathFunctionRegistry` loads `spec/math-functions.v1.json` and references existing `kernel_id` implementations.
3. It verifies that every referenced kernel exists, is `native_verified`/CI-verified, and has matching precision/shape/workspace.
4. It exposes `lookup`, `resolve`, `compose`, `validate_contract`, and `health`.
5. `MthPlan` remains the execution plan; `NmpPlan` wraps it with math/rule/preflight context.
6. No existing test or manifest entry is invalidated by the new layer.

This avoids a flag day while preserving the 61-kernel manifest and its CI evidence.

Compatibility constraints:

- do not add/remove entries in `spec/wave-capabilities.json` to represent functions; the 61-kernel count is pinned;
- do not add required fields to `MthKernelDescriptor` or `MthPlan` v1; optional extension fields must default and leave v1 serialization byte-identical;
- do not change `KERNEL_STATUSES`/`PRECISIONS` for new semantics; use separate enums in the math registry;
- keep `MthPlan.to_dict()` v1 unchanged; add `to_v2_dict()`/`NmpPlan` for `plan_digest`, typed pins, admission, and peak workspace;
- keep `WaveStore.SCHEMA_VERSION=1`; add `math_*` tables under a separate `math_schema` row, then a later explicit migration if needed;
- run `test_mth_registry`, `test_mth_system`, `test_wave_capabilities`, `test_wave_store`, and the full 653-test suite after every change.

### 6.3 Initial function catalogue

The first v1 catalogue should be small and complete enough to prove the architecture:

| Function | Inputs | Output | Implementation |
|---|---|---|---|
| scalar add/sub/mul/div | scalars, compatible domains | scalar | existing scalar kernels |
| vector add/sub | vectors, same shape/domain | vector | existing/Future kernel |
| dot | two equal vectors | scalar | `mth.vector.dot256.f32` |
| norm | vector | scalar | `mth.vector.norm256.f32` |
| cosine | two vectors | scalar | `mth.vector.cosine256.f32` |
| distance | two vectors | scalar | norm composition |
| axpy | scalar, vectors | vector | `mth.vector.axpy256.f32` |
| matvec | matrix, vector | vector | `mth.matvec*` |
| matrix multiply | matrices | matrix | product kernels |
| transpose | matrix | matrix | future/native |
| projection | matrix/vector | vector | composition |
| top-k | scores, k | indices/values | `mth.topk.256.f32` |
| hyperedge construction | members/roles | relation | relation registry |
| equality | typed values | Boolean | typed equality kernel or exact-byte path |
| hash | canonical leaf | digest | host digest or native hash binding |

The catalogue is a vocabulary, not a claim that every family is complete.

### 6.4 Composition

Composition is contract satisfaction:

```
f: A -> B
g: B -> C
g∘f: A -> C   only if output_contract(f) satisfies input_contract(g)
```

The output must match type/domain/shape/precision and any required invariants. Composition creates a new function leaf; it does not require a new native CPU instruction for every combination. If composition is promoted to a fused kernel, the original mathematical provenance is preserved and the fused kernel must pass the same contract and evidence gates.

### 6.5 Rule registry

A rule has:

- `rule_id`, version, level (0–3), scope;
- input/output contracts;
- preconditions, invariants, postconditions;
- undefined conditions;
- numerical/execution policy;
- proof status (`axiom`, `proven`, `verified`, `tested`, `empirical`, `experimental`, `rejected`);
- references to certificates/tests;
- digest and status (`proposed`, `validated`, `active`, `deprecated`, `revoked`).

Levels:

| Level | Authority | Can it be learned? |
|---|---|---|
| 0 | axioms, type safety, domain compatibility | no; immutable/pinned |
| 1 | registered function contracts | changes require formal review |
| 2 | derived rules with derivations/certificates | yes, with proof/verification |
| 3 | experimental learned rules, isolated | yes, but cannot execute outside isolation |

A level-3 rule can propose; it cannot silently change level 0 or 1. Promotion is a separate, transactional operation.

### 6.6 Compatibility index

For performance, maintain a deterministic compatibility index:

```
key = (type_a, type_b, domain_a, domain_b, shape_class)
value = ordered candidate function IDs
```

The index is a cache, not authority. It is invalidated by function/rule version changes. The validity engine still checks every selected candidate.

### 6.7 Relation and hyperedge contracts

A hyperedge is an explicitly defined relation, not an arbitrary bag of objects. Its schema records:

- `relation_id`, version, schema;
- member leaf IDs/versions and optional roles;
- ordered/unordered;
- duplicate-member policy;
- directed/undirected;
- weights and weight domain;
- required shared domains or explicit cross-domain permission;
- arity/n-ary constraints;
- required constraints/invariants;
- provenance and rule snapshot.

A hypergraph is a relation leaf whose members reference other relation leaves or object leaves. Recursive composition is allowed only through bounded, registered relation schemas. The system enforces maximum depth and fan-out; no schema may create an unbounded implicit expansion. A relation leaf can be an input to `::`, but only relation functions whose contracts accept it. It is not automatically a container for vectors, functions, rules, and arbitrary JSON.

### 6.8 Universal function references and `XFSC365`

A function reference such as `XFSC365` is an **opaque semantic identity**, not a number that encodes the function body. It resolves through MC0DB to a versioned contract:

```
XFSC365
  -> function_id / version / contract_digest
  -> input/output signatures and domains
  -> pre/postconditions and undefinedness
  -> implementation bindings (symbolic/CPU/parallel/distributed)
  -> proof/test status
```

Multiple implementations may satisfy the same function identity; each implementation has its own digest, precision, capability class, workspace, and evidence. The linker selects the function identity; the scheduler selects an implementation/capability. Replacing a slow implementation must not change the mathematical identity or silently change the contract.

### 6.9 There is no finite complete function list

The registry is complete for the **system's supported primitives and composition rules**, not for all mathematics. New functions are admitted only through the same contract/preflight process. An LLM or learning head may propose a function name or a candidate contract; that proposal has no authority until it is hashed, validated, tested/proven as required, and activated in a new snapshot. This is the safeguard against "the model invented a function, therefore it is valid."

---

## 7. The `::` linker

### 7.1 Meaning

`::` means:

> Given two or more resolved mathematical leaves and a current rule/function snapshot, enumerate the transformations that are *candidates* for this conjunction, with enough information for a separate validity engine to decide.

It does **not** mean addition, multiplication, concatenation, dot product, or authorization.

### 7.2 Pipeline

```
INPUT: A :: B [:: C ...]
 1. parse math-expression context
 2. resolve leaf IDs, versions, content digests, and storage refs
 3. classify type, domain, shape, precision, relation schema
 4. snapshot function/rule versions and capability set
 5. compute compatibility candidates
 6. rank candidates deterministically for the caller's objective
 7. return a candidate set, never execute implicitly
 8. optional: selected candidate -> NMP packet -> validity preflight
```

### 7.3 Candidate set fields

```json
{
  "schema": "nanrouter.math-candidate-set.v1",
  "snapshot_id": "sha256:...",
  "linker_id": "math.linker.v1",
  "inputs": [
    {"leaf_id": "...", "version": 1, "content_digest": "..."}
  ],
  "functions": [
    {
      "function_id": "math.vector.dot.v1",
      "version": 1,
      "contract_digest": "...",
      "result_type": "scalar",
      "preflight_hint": "candidate",
      "rank": 1,
      "reason": "registered vector/vector operation"
    }
  ],
  "rejected": [
    {"function_id": "...", "reason": "dimension mismatch"}
  ],
  "candidate_count": 1
}
```

The candidate set is evidence, not an execution authorization.

### 7.4 Ranking and bounded exploration

Ranking may use declared static features (signature fit, expected result type, learned utility, cost). It must be deterministic for a given snapshot and objective. It must never change validity.

The linker should support:

- enumerate all valid candidates;
- rank candidates;
- execute a selected candidate;
- execute a bounded candidate batch;
- return no transform;
- return a typed null with a reason.

The default should be **propose and stop**. Automatic execution is an explicit caller choice with a bounded candidate count.

### 7.5 Candidate deduplication

Deterministic operation key:

```
K = SHA256(
  canonical_input_identities,
  input_versions,
  input_digests,
  function_id/version/contract_digest,
  rule_snapshot_digest,
  numerical_policy,
  canonical_operand_order_if_commutative
)
```

Order-sensitive operations preserve operand order. Commutative functions canonicalize operands only if the function contract explicitly declares commutativity. The in-flight table subscribes duplicate requests to the existing result instead of recomputing.

### 7.6 Address-context rejection

The linker must reject:

- `nan://` route strings as operands;
- `HW0:...` without an explicit leaf alias;
- raw numeric offsets as leaf IDs;
- a candidate whose function contract is not from the current snapshot;
- a candidate whose implementation is unavailable if the caller requires execution.

---

## 8. Mathematical validity engine

### 8.1 Authority

The validity engine is the only writer of a **preflight authorization** for a candidate. Its output is not a recommendation. A candidate without a current `VALID` preflight cannot enter `MthSystem`, a runner lease, or a remote executor.

### 8.2 Preflight order

```
1. schema/parse validity
2. leaf existence and version pinning
3. type/domain/shape/precision compatibility
4. function contract (level 1)
5. load-bearing rule levels 0 and 2
6. numeric precondition policy (native certificate if required)
7. authorization/ACL
8. capability/availability (separate result; not math validity)
9. resource window (guest words, fuel, depth, fan-out)
10. snapshot lock and preflight digest
```

### 8.3 Result classes

| Result | Meaning | May execute? |
|---|---|---:|
| `VALID` | all math/type/rule checks pass and authorization permits | yes, with capability |
| `INVALID` | structurally or mathematically incompatible | no |
| `UNDEFINED` | valid operation but undefined for these inputs/domain | no |
| `UNAUTHORIZED` | ACL/policy rejects this requester | no |
| `UNSUPPORTED` | no implementation for the requested form | no |
| `UNAVAILABLE` | implementation exists but runner/capability unavailable | no |
| `STALE` | rule/function/leaf snapshot changed | retry preflight |
| `EXPERIMENTAL` | level-3 isolated candidate | only isolated execution |
| `UNKNOWN` | precondition not established | no |

`UNAVAILABLE` is not `NULL`. A missing runner is a resource state.

### 8.4 Rule levels and immutability

- Level 0 rules are pinned and cannot be learned or overwritten.
- Level 1 changes are versioned and require review/testing.
- Level 2 derivations require a derivation/certificate and can be promoted transactionally.
- Level 3 proposals are isolated; their outputs cannot become production leaves without promotion.

A contradiction between two rules is flagged and blocks the affected functions; the engine never selects the most recently learned rule.

### 8.5 Preflight cache

```
key = SHA256(
  leaf_ids + versions + content_digests,
  function_id + function_version + contract_digest,
  rule_snapshot_id,
  numerical_policy,
  authorization_context,
  capability_requirement
)
```

A changed input, function, rule, policy, or authorization context invalidates the cache entry. Cached results carry the same snapshot digest and expire on rule promotion/rollback.

### 8.6 No host mathematics

The host may compare metadata, hashes, type names, and declared bounds. If a precondition requires numerical evaluation (for example, a provable invertibility certificate, a norm threshold, or a residual bound), the preflight must dispatch a native certificate kernel or return `UNKNOWN`/`UNSUPPORTED`. The host must not approximate a mathematical precondition in Python.

---

## 9. NMP: NaN Mathematical Protocol

### 9.0 Placement: host control, not native state

NMP is a **host-control envelope**. Queue state, leases, dedupe, ACL, cancellation epochs, capability checks, and crash recovery belong in Python/BS0DB/MC0DB. Native NaN16 receives only selected payload words and the JAHS seal gate. Native code may check a 64-bit packet tag or seal; it must not own durable state or cancellation policy.

A batch is one parent NMP packet plus N ordinary child jobs. There is no parent lease and no second job ledger. Each child is leased/completed independently so a handoff can occur between children.

### 9.1 Purpose

NMP is the typed packet/state machine that carries a selected candidate through preflight, authorization, scheduling, execution, and evidence. It is a control-plane protocol; native kernels still perform the mathematics.

### 9.2 Packet fields

```json
{
  "schema": "nanrouter.nmp.v1",
  "packet_id": "nmp:...",
  "state": "PROPOSED",
  "snapshot_id": "sha256:...",
  "parent_packet_id": null,
  "batch_id": "sha256:...",
  "batch_index": 0,
  "batch_count": 15,
  "lane_id": 0,
  "universe_id": "U0",
  "generation": 7,
  "base_generation": 7,
  "epoch": 3,
  "operation_id": "op:...",
  "registry_digest": "sha256:...",
  "plan_digest": "sha256:...",
  "capability_set_digest": "sha256:...",
  "linker_id": "math.linker.v1",
  "function_id": "math.vector.dot.v1",
  "function_version": 1,
  "ruleset_id": "math.rules.core.v1",
  "ruleset_version": 1,
  "inputs": [
    {"leaf_id": "...", "version": 1, "digest": "..."}
  ],
  "preflight": {
    "result": "VALID",
    "rule_level": 1,
    "digest": "sha256:...",
    "reason": null
  },
  "capability": {
    "required": "vector.dot",
    "selected_runner": "MC0:0/R0",
    "implementation_id": "mth.vector.dot256.f32"
  },
  "resources": {
    "guest_words": 256,
    "fuel": 1000000,
    "deadline_tick": 123
  },
  "output": {
    "leaf_id": null,
    "digest": null,
    "kind": "scalar"
  },
  "evidence": {
    "job_id": null,
    "lease_epoch": null,
    "ring_incarnation": null,
    "ring_epoch": null,
    "result_status": null,
    "jahs": "JAHS"
  }
}
```

### 9.3 States

```
CREATED -> RESOLVED -> CLASSIFIED -> PROPOSED -> PREFLIGHTED
      -> QUEUED -> EXECUTING -> COMPLETED -> COMMITTED
```

Terminal/failure branches:

```
NULL, UNDEFINED, REJECTED, UNAVAILABLE, FAILED, CANCELLED, STALE
```

Invalid transitions must fail closed. A packet cannot jump from `PROPOSED` to `EXECUTING`; `COMMITTED` requires output digest and provenance; `FAILED` is not `NULL`; `CANCELLED` is not a mathematical result.

Minimum transition table:

| From | Allowed next |
|---|---|
| CREATED | RESOLVED, REJECTED, CANCELLED |
| RESOLVED | CLASSIFIED, INVALID, NULL, CANCELLED |
| CLASSIFIED | PROPOSED, INVALID, UNDEFINED, CANCELLED |
| PROPOSED | PREFLIGHTED, NULL, REJECTED, CANCELLED |
| PREFLIGHTED | QUEUED, UNAVAILABLE, UNAUTHORIZED, STALE, EXPERIMENTAL, CANCELLED |
| QUEUED | EXECUTING, CANCELLED, FAILED |
| EXECUTING | COMPLETED, FAILED, CANCELLED |
| COMPLETED | COMMITTED, FAILED |
| COMMITTED | terminal (except evidence append/repair) |
| NULL/UNDEFINED/REJECTED/UNAVAILABLE/UNAUTHORIZED/STALE/FAILED/CANCELLED | terminal for this packet |

### 9.4 Snapshot identity

Every packet binds to a snapshot of:

- leaf versions;
- function/rule versions;
- implementation/capability set;
- numerical policy;
- runner epoch.

A result computed under another snapshot is not silently accepted. It may be retained as historical evidence but cannot satisfy the current request.

### 9.5 Deduplication and in-flight table

The operation key from §7.5 indexes in-flight and completed results. Duplicate packets in the same snapshot subscribe to the existing result. A duplicate with a different snapshot, rule version, or numerical policy is a distinct operation.

### 9.6 State storage

The packet is a compact canonical record. Large payloads live in BS0DB; the packet holds references/digests. The packet and its transitions are append-only evidence in BS0DB; current state is an MC0DB index. No packet contains a secret.

### 9.7 Cross-store commit protocol

BS0DB and MC0DB are separate SQLite stores. Do not claim a distributed transaction. Use a crash-consistent intent/finalize protocol:

```
1. MC0DB: insert commit intent (rule/leaf, evidence digest, base generation)
2. BS0DB: append evidence idempotently; verify digest
3. MC0DB: BEGIN IMMEDIATE; verify generation/digests; insert version/mapping;
   mark intent finalized; COMMIT
4. recovery: pending intent + matching evidence -> finalize;
   missing/mismatch -> fail; no partial active mapping
```

The claim is "crash-consistent with idempotent replay," not "atomic across two databases." Every recovery path must be tested (see §20.8).

---

## 10. NaNNet meta-mapping and storage

### 10.1 Ownership

| Store | Owns | Does not own |
|---|---|---|
| BS0DB | mathematical payloads, canonical leaf content, append-only traces/seals/signatures | rule authority, routing authority |
| MC0DB | function/rule/validity catalog, capabilities, job/lease indexes, NMP state, mapping versions | bulk payloads |
| NANNET metadata | identities, routes, storage locations, subgraph definitions, version pointers | numerical results, rule truth |
| Runner cache | disposable local copies/indexes | canonical state |

The three database namespaces can be physical databases or logical partitions; the ownership contract must not change.

### 10.2 Proposed tables (separate math schema, backward compatible)

MC0DB:

- `math_leaf`: `leaf_id`, current version, kind, type digest, content digest, status, created/updated ticks.
- `math_leaf_version`: `leaf_id`, `version`, content digest, parent refs, operation ref, provenance, immutable payload ref.
- `math_function`: `function_id`, current version, contract digest, status, proof status.
- `math_function_version`: full canonical contract/implementation bindings.
- `math_rule`: `rule_id`, level, current version, status, scope.
- `math_rule_version`: contract, proof status, test/certificate refs, digest.
- `math_relation`: relation ID, schema, member refs, constraints, version.
- `math_candidate`: candidate set ID, snapshot ID, input refs, function refs, rank, outcome.
- `math_mapping`: stable identity -> current version/storage tier/route.
- `math_preflight_cache`: cache key, snapshot, result, expiry/invalidation digest.
- `math_nmp_packet`: packet ID, state, snapshot, job/lease refs, result digest.

BS0DB:

- `math_payload`: content digest, encoding, length, blob, created tick (append-only).
- `math_event`: append-only propose/preflight/execute/commit/null/void/rollback events.
- `math_certificate`: native residual/proof/test certificates.

Do not duplicate the existing `wave_operator`/`wave_capability` tables. They remain implementation/capability facts and are joined to `math_function_version` by kernel ID/digest.

Backward-compatibility rule: the current `wave_schema`/`SCHEMA_VERSION=1` contract is pinned by tests. Add the `math_*` tables with `CREATE TABLE IF NOT EXISTS` and a separate `math_schema` row; do not bump `wave_schema` in the same change. A later `wave_schema` v2 migration requires its own backup/rollback test. This preserves the 61-kernel and store tests while the mathematical layer grows.

### 10.3 Mapping versions and transactions

A mapping update is:

```
prepare new version
  -> validate target leaf/function/rule
  -> write immutable payload/version
  -> compare-and-swap current pointer with expected version
  -> append mapping event
  -> publish cache invalidation
```

The old pointer remains recoverable. A failed CAS leaves the old mapping active. A rollback is a new mapping event, not a destructive update.

### 10.4 Cache and recovery

- Caches are disposable; eviction never deletes canonical data.
- A cache miss resolves through NANNET metadata to BS0DB/MC0DB.
- A corrupt/missing payload is a reference error, not zero/null.
- Recovery reconstructs current mappings from immutable version rows and the append-only event log.
- A stale cache entry is rejected by generation/version/digest checks.

---

## 11. Execution ring, 255 logical lanes, and capabilities

### 11.1 Do not claim 255 simultaneous runners

The existing ring has **six slots**, exactly one active at a time, with a 7 GiB active-runner ceiling. The 255 logical lanes are scheduling/role classes, not 255 concurrent native processes or 255 active runner slots.

A logical lane can be:

- an in-process work queue;
- a virtual head/task class;
- a native worker lane within the one active slot;
- a remote worker class only when the architecture supports it.

The invariant remains:

```
one active runner slot at a time
all live execution/leases/memory on that slot
handoff after checkpoint, lease drain, and memory release
```

### 11.2 Canonical lane identity and pass schedule

The cleanest mapping is one logical lane per head:

```
lane_id       = 0..254
NANNET0       = ring position 255, not a lane
255 lanes     = 17 groups x 15 lanes
lane state    = one 32 KiB home page or a small page-set
heavy matrix  = transient page-set, not per-lane persistent state
```

A deterministic pass processes lanes `15p .. 15p+14`; at every instant:

| Resource | Count |
|---|---:|
| declared logical lanes | 255 |
| executing lane runs | **1** |
| active runner slots | **1** |
| standby slots with live working sets | **0** |
| native kernel invocations in flight | **1** |
| live guest working set | one adjustable budget (target 2 MiB) |

A full sweep is 17 passes. The six slots rotate behind the queue; a lane is a durable work identity, not a runner.

Memory discipline: 255 lane home pages × 32 KiB = 7.97 MiB, which fits the 256-page universe (255 heads + NANNET0). One 256×256 float32 matrix is **65,536 guest words = 512 KiB = 16 pages**, not 8 pages / 256 KiB; 255 such matrices would be 127.5 MiB and do not fit the 8 MiB universe. Heavy matrices are transient page-sets, not per-lane persistent state. The 7 GiB ceiling is not multiplied by 255.

The 12 function groups are **10 lane-local stages** (address resolution, classification, function lookup, preflight, execution, hypergraph, hashing, learning, memory, pruning) plus **2 global authorities** (scheduling and supervision). Per-lane schedulers/supervisors would duplicate the ring authority and are forbidden.

### 11.3 Logical head roles

The proposed roles are a useful initial vocabulary, not hard partitions:

| Logical range | Role |
|---|---|
| H00–H15 | address resolution, identity verification |
| H16–H31 | classification/type analysis |
| H32–H63 | function lookup/candidate generation |
| H64–H95 | preflight/constraint validation |
| H96–H159 | numerical/symbolic execution |
| H160–H191 | hypergraph/relation construction |
| H192–H207 | hashing/provenance/commit |
| H208–H223 | learning/evaluation/rule proposals |
| H224–H239 | memory indexing/retrieval |
| H240–H247 | pruning/resource management |
| H248–H253 | scheduling/coordination |
| H254 | supervisory validation/fault coordination |

The scheduler may borrow idle lanes for independent work, except for critical control functions. Capability declarations prevent a numerical lane from executing a preflight-only op and vice versa.

### 11.4 Work queues and work stealing

- Each logical role has a bounded queue.
- Work stealing moves independent NMP packets, never partially executing packets.
- A stolen packet carries its snapshot, preflight digest, capability requirement, and fuel.
- A runner may reject a stolen packet if capability/capability version does not match.
- Critical preflight/control queues cannot be starved by speculative execution.
- Fan-out and recursion depth are bounded before enqueueing.

### 11.5 Capabilities

A capability is a deployment fact:

```
runner_id, implementation_id, function_id, version/digest,
precision, workspace, status, epoch, max_fanout
```

A function can be:

- mathematically valid and locally executable;
- valid but requires another implementation/runner;
- valid but currently unavailable;
- valid but unauthorized.

These are separate from `NULL`/`UNDEFINED`.

### 11.6 Determinism

For each function, declare:

- precision and rounding;
- reduction order;
- FMA/reassociation policy;
- NaN/Inf handling;
- deterministic vs nondeterministic implementations;
- serialization/normalization rules.

Identical inputs and rule snapshots should produce identical canonical results when the contract promises determinism. If an implementation is nondeterministic, its result must be tagged and cannot silently satisfy a deterministic contract.

### 11.7 Integration with existing runtime

- `MthSystem` remains the facade. A new `NmpRuntime`/`MathRuntime` composes it rather than replacing it.
- `MthPlan` remains the typed execution plan; `NmpPlan` wraps it with leaf/rule/preflight context.
- `WaveService.submit_job` receives a job whose payload contains the NMP snapshot/preflight digest.
- `WaveRingScheduler` lease/epoch/capability checks remain authoritative for the active slot.
- `Point0Router` remains the only public ingress; `JAHS` seals every handoff and point-0 request.
- `WaveStore` gains additive math tables; no second lease ledger.
- A native executor receives only a selected, preflighted step with explicit pointers and workspace.

---

## 12. Null, void, undefined, and absence

### 12.1 Rules

- `NULL` is a typed result state, not numeric zero.
- `VOID` means no mathematical object exists; it is not a wildcard.
- `UNDEFINED` means the operation is mathematically undefined for these inputs.
- `EMPTY` is a valid empty structure.
- `INFINITY` is valid only where the domain permits it.
- `UNKNOWN` means not established; it may become known later.
- `ERROR` is execution failure; it is not a mathematical result.

### 12.2 Conjunction semantics

| Expression | Default result |
|---|---|
| `OBJECT :: VOID` | `UNKNOWN` if input could arrive; reference error if required object missing |
| `VOID :: OBJECT` | same asymmetry policy |
| `VOID :: VOID` | explicit `VOID` result or reference error by rule |
| `NULL :: OBJECT` | no candidates unless a registered null algebra exists |
| `UNDEFINED :: OBJECT` | no candidates; preserve reason |
| `OBJECT :: UNDEFINED` | no candidates; preserve reason |
| `OBJECT :: NULL` | candidate set empty; preserve parents/reason |

A null leaf is feedback evidence, not a permanent prohibition. A later function/rule version may make the conjunction valid.

---

## 13. Learning, rule discovery, and proof status

### 13.1 Five learning mechanisms

| Mechanism | Learns | Must not learn |
|---|---|---|
| Structural | types/shapes/domains/relations | new axioms from co-occurrence |
| Transformational | registered input→output contracts | arbitrary correlations as functions |
| Derivational | composition and equivalent rewrites | unproved identities as proven |
| Relational | graph/hypergraph neighborhoods and usefulness | truth from popularity |
| Operational | caching, scheduling, parallelization, pruning | mathematical validity from performance |

### 13.2 Rule lifecycle

```
PROPOSED -> HASHED -> VALIDATED -> TESTED -> PROVEN/VERIFIED
         -> APPROVED -> ACTIVE -> DEPRECATED -> REVOKED
```

Each transition is an append-only event. Activation is transactional: new calculations use the new rule snapshot; in-flight calculations keep their original snapshot. A contradiction blocks promotion and identifies affected functions/rules.

### 13.3 Proof status

`axiom`, `proven`, `verified`, `tested`, `empirical`, `experimental`, `rejected`.

A numerical test is not a proof. A million random successes do not establish universal distributivity. The plan must state the exact scope of every claim.

### 13.4 Learning heads and Boolean decisions

Boolean-level heads may:

- propose rule changes;
- classify candidate validity evidence;
- detect contradictions;
- rank candidates for an objective;
- recommend promotion.

They may not:

- change level 0 rules;
- write an active mapping without the transaction protocol;
- authorize their own candidate;
- execute a candidate before preflight;
- treat task benefit as proof.

### 13.5 Not by association, popularity, or performance

A mathematical rule is **not** established by:

- co-occurrence frequency;
- embedding proximity;
- how often a head proposes it;
- the rank/score assigned by the linker;
- task accuracy on one dataset;
- gradient descent over model weights;
- novelty or unusual output;
- majority vote of heads;
- recency or last-writer-wins.

Those may be discovery signals, ranking features, or experimental evidence. They are not proof. A rule becomes active only through the proof/validation policy of its level. A rule's numerical or empirical status must be stored explicitly; it cannot masquerade as an axiom.

### 13.6 LM/R7 integration

- The LM adapter remains a bounded residual experiment (`h + beta*C*u`), not a new math authority.
- R7 and capacity experiments consume native evidence and use explicit gates.
- No real LM/data experiment is claimed until a frozen model/data harness exists.
- A task-benefit result can promote an **experimental** rule for further testing; it cannot promote a mathematical axiom.

### 13.7 Self-modification classes

| Class | Examples | Authority |
|---|---|---|
| A — automatic | cache order, index rebuild, scratch cleanup, ranking/retention updates | system, audited, reversible |
| B — authorized CAS | mapping/activation changes, rule deprecation, prune plan | separate `rule.activate`/`rule.prune` + approval; rollback plan |
| C — out-of-band | executable code, proof checker/validity semantics, schema, ACL root, control identities, live routes | owner/multi-party policy upgrade; never during normal learning |

A proposal may not validate itself, approve itself, modify its own checker, change a control head, or write a live route table. Class C changes require a signed policy transition and a full regression run.

### 13.8 Experiment outcomes are not validity

`supported` (R7) and `ablation_passed` (LM adapter) are `experiment_outcome` values. They may support utility/ranking or an enablement recommendation; they must never set `validity_level`, `truth_status`, or `proof_status`. Missing, synthetic, or underpowered data is `inconclusive`; fake evaluators prove harness mechanics only. A native-verification record and a separate cost/latency gate are required before enabling an adapter or learned head.

---

## 14. Scratch, oscillation, pruning, and retention

### 14.1 Scratch

Scratch leaves are:

- explicitly non-authoritative;
- bounded by the active guest budget;
- not visible to the linker unless a caller opts in;
- deleted or compacted after evidence retention;
- never eligible for promotion without a new commit/preflight.

### 14.2 Oscillation cycle

```
OBSERVE -> CLASSIFY -> CONJOIN -> PROPOSE -> PREFLIGHT
        -> SELECT -> EXECUTE -> COMMIT -> EVALUATE
        -> (MODIFY / REPEAT / STOP)
```

Every oscillation carries:

- snapshot ID;
- depth;
- fan-out;
- fuel;
- candidate-count budget;
- duplicate-set key;
- stop reason.

Stop conditions include fuel exhaustion, no valid candidates, no new content hash, repeated state, contradiction, and operator cancellation.

### 14.3 Retention score

A starting point:

```
R(x) = w_u*Utility + w_r*RelationImportance + w_d*DerivationValue
     + w_p*PredictiveUsefulness + w_c*RecomputeSavings
     - w_s*StorageCost
```

The weights are learned operational policy. They may decide cache tier/eviction, never truth. Structural importance (dependency count, reuse) is separate from recency.

### 14.4 Tiers

| Tier | Contents | Eviction |
|---|---|---|
| Active | runner registers, hot leaves, active subgraphs, scratch | evict safely; never delete canonical payload |
| Persistent | BS0DB/MC0DB leaves, rules, versions | retained; garbage collect only with provenance policy |
| Archived | cold versions, reproducible intermediates | recoverable/recomputable |

Pruning removes cache entries or recomputable scratch; it does not erase mathematical truth without an explicit retention/legal policy.

---

## 15. Security, authorization, and bounds

- Every mutating operation has an authenticated principal and ACL scope.
- Every execution carries a lease/epoch/generation and JAHS seal.
- Every preflight authorization is digest-bound and snapshot-bound.
- A changed rule/leaf/capability invalidates authorization.
- Secrets never enter leaves, NMP packets, logs, or evidence.
- Recursion depth, fan-out, candidate count, fuel, workspace, packet size, and network timeout are bounded.
- A denied operation is audit-recorded, not silently converted to null.
- Remote workers receive only the selected step/payload and cannot reinterpret a rule.
- Rule promotion requires stronger authorization than rule proposal.
- No hidden host math: a native certificate is required for numerical preconditions that cannot be established structurally.
- JAHS ("Just A Handoff Seal") remains a mandatory execution/handoff seal; it is not a mathematical validity authority. The old noosphere/JAHS language remains a non-normative easter egg; the normative math path is NANNET0 + MTH.

---

## 16. 2 MiB memory integration

### 16.0 Guest words versus raw IEEE bytes

One NaN16 guest word is 8 bytes. A packed float32 payload is 4 bytes. These must not be mixed:

| Object | Guest words | Guest bytes | Pages of 32 KiB | Raw packed f32 |
|---|---:|---:|---:|---:|
| 256×256 float32 | 65,536 | 524,288 (512 KiB) | 16 | 262,144 (256 KiB) |
| 255×255 float32 | 65,025 | 520,200 (~508 KiB) | 16 | 260,100 |
| 256×256 complex float32 (two planes) | 131,072 | 1,048,576 (1 MiB) | 32 | 524,288 (512 KiB) |
| full 256 pair U+L+output | 196,608 | 1,572,864 (1.5 MiB) | 48 | 786,432 |
| 512×512 dense float32 | 262,144 | 2,097,152 (2 MiB) | 64 | 1,048,576 |
| dense 65,536² | 4,294,967,296 | 34,359,738,368 (32 GiB) | 1,048,576 | 17,179,869,184 (16 GiB) |

Admission uses guest words/pages; raw packed bytes are a storage/transport detail only. At 2 MiB, 196,608 words (48 pages) fits with 64,512 words spare; a fourth 256×256 matrix (262,144 words) exactly fills the guest and is not practical with code/scratch. One complex matrix is practical; two complex matrices (262,144 words) are not.

The page-backed pair executor adds a concrete worker-budget example. A K16 driver workspace is 17,170 words and the full-U reference is 73,990 words. At 1 MiB, `3*17,170 + 73,990 = 125,500` words fits and a fourth worker is rejected. At 2 MiB, up to **10** K16 workers plus the reference fit by aggregate arithmetic (`10*17,170 + 73,990 = 245,690` words); 11 do not (`262,860`). This is an **admission calculation**, not proof of physical parallelism: the runtime must provide independent worker slots and the coordinator still serializes the dense reference. The single-active-slot rule is unchanged.

### 16.1 Budget model

```
guest_bytes  = declared adjustable budget (target 2 MiB)
guest_words  = guest_bytes / 8
page_bytes   = 32 KiB
guest_pages  = guest_bytes / page_bytes
```

Effective plan budget:

```
effective_words = min(guest_words, runner_workspace_words, plan_workspace_words)
```

Reject before store/service submission if the plan's conservative workspace exceeds the effective budget.

### 16.2 What changes at 2 MiB

- Full 256 `U + L + output` pair becomes guest-feasible in one window (196,608 words, 1.5 MiB); still use K16/page windows for production and concurrency.
- Full 256 SVD/eigen work with basis/scratch becomes plausible; numerical stability and recurrence still dominate.
- Complex 256 matrices fit with scratch.
- The 2 MiB guest holds 64 of the 256 universe pages.
- Point-0 frames can carry 262,144 words; full 256×256 float32 is 512 KiB of that.
- A 512×512 dense matrix exactly fills 2 MiB and is not a supported general workload.
- The dense 65,536² product remains forbidden at 16 GiB (float32 payload) / 32 GiB (8-byte NaN words).

### 16.3 Required 2 MiB tests

1. Default budget reports 262,144 words and 64 pages.
2. Explicit 1 MiB override reports 131,072 words/32 pages and rejects 2 MiB-only plans.
3. Explicit 4 MiB override is accepted only if the platform declares it.
4. A plan at exactly the effective limit is accepted; one word over is rejected before store mutation.
5. Full 256 pair `U+L+output` plan is admitted at 2 MiB and rejected at 1 MiB.
6. Point-0 accepts exactly 262,144 words and rejects 262,145.
7. 512 KiB compatibility mode rejects 2 MiB-only fixtures.
8. Health/evidence records the budget source and page count.
9. No default silently changes from 1 MiB to 2 MiB without a versioned migration test.
10. GLT-enforcement remains a separate gate.

### 16.4 Exact code points GPT must synchronize

When the 2 MiB branch is merged, update and test at least:

| Location | Current (1 MiB) | Target (2 MiB) |
|---|---|---|
| `MthSystem.DEFAULT_GUEST_BUDGET_BYTES` | `2 * 1024 * 1024` | implemented |
| `MthSystem` health `guest_budget_words` | 262,144 | implemented |
| `MthSystem` health `guest_budget_pages` | 64 | implemented |
| `Point0Bridge.MAX_FRAME_WORDS` | 262,144 | implemented |
| `register_wave_capabilities.DEFAULT_GUEST_WORKSPACE_WORDS` | 262,144 | implemented |
| MTH memory docs/examples | 2 MiB + 1 MiB/512 KiB modes | updated |
| CI budget fixtures | 2 MiB boundary + legacy modes | add/verify in the next CI run |
| `guest_budget_words` primary input | words-first adjustable budget | implemented |

The target is `guest_words`, not a hidden hard-coded assumption. A deployment may override it; a plan may not silently ignore it.

---

## 17. End-to-end v1 demonstration

### 17.1 Fixture

Use canonical mathematical leaf references, not bare head IDs:

```
L0:123 = vector<128, real, float32>
L0:234 = vector<128, real, float32>
```

### 17.2 Sequence

1. Commit two vector leaves through the leaf registry; verify content hashes and provenance.
2. Call `::` on `L0:123` and `L0:234` with the core function/rule snapshot.
3. Receive candidate set: `dot`, `euclidean_distance`, `cosine_similarity`, `add`, `subtract` (only those whose contracts currently fit).
4. For each selected candidate, preflight; store `VALID`/`INVALID` evidence.
5. Select `dot`; create an NMP packet with snapshot/preflight digest.
6. Submit through `MthSystem`/point 0; lease to the active slot; execute `mth.vector.dot256.f32` (or the registered implementation); commit the scalar result leaf `L0:345`.
7. Verify `L0:345` has parents, function/rule versions, output hash, JAHS seal, and evidence.
8. Feed `L0:345` into a hypergraph relation and observe candidates; do not auto-execute.
9. Re-run with a mismatched dimension, stale rule, unavailable capability, and unauthorized principal; verify distinct failure states.
10. Confirm no host-side mathematical result was computed.

### 17.3 Acceptance

A valid, hashed, addressable mathematical structure exists with complete provenance and a reusable transformation definition; every negative case returns the correct typed state, not a generic null.

---

## 18. Integration map to the existing repository

| Existing anchor | Keep | Add / change | Risk |
|---|---|---|---|
| `MthRegistry` / `MthPlan` | execution/implementation registry and typed plan | new `MathFunctionRegistry` references kernels; `NmpPlan` wraps plan + rule snapshot | do not change 61-kernel manifest semantics |
| `MthSystem` | registry/store/service/scheduler facade; 1 MiB/2 MiB budget | new `NmpRuntime` composes it; no second lease/store | validate preflight before submit; preserve JAHS |
| `WaveStore` | BS0DB/MC0DB existing tables | additive `math_*` tables + separate `math_schema`; keep `wave_schema=1` until explicit migration | no duplicate truth/lease authority |
| `WaveService` | auth/role boundary | accept math job payload with preflight digest; reject missing/stale | no secret leakage |
| `WaveRingScheduler` | six-slot single-active ring | logical lane mapping outside scheduler; capability checks | don't claim 255 concurrent runners |
| `Point0Bridge` / `Point0Router` | stable ingress, active slot evidence, JAHS | `/v1/math/link` and `/v1/math/execute` use NMP; no direct slot | `::` address collision |
| `WaveHTTP` / `Point0HTTP` | authenticated HTTP | math endpoints; bounded 2 MiB frames; redaction | body limits/timeouts |
| `MthKernelDescriptor` | native implementation facts | semantic contract in `MathFunctionVersion` | one function, multiple implementations |
| `spec/wave-capabilities.json` | implementation manifest | leave unchanged; new `spec/math-functions.v1.json` | mth IDs remain stable |
| `wave_tile_orchestrator` | 256-tile page publication | NMP candidate batches can use it for pair ops | evidence binding |
| `mth_pair_file_pages` | immutable 16×16 page files, pinned snapshots, CAS output generations | 2 MiB worker admission must include page-strip/reference workspace; no provider mount assumed | local adapter only; not deployed |
| `mth_pair_tile_executor` | K16 page-backed executor + full-U cross-check | bind candidate output to tile manifest and page-store CAS | guest adapter still missing; parallel budget is aggregate |
| `live_preflight` | offline/live gates | include math store/rule registry checks | no live credentials in tests |
| `lm_ablation` / `r7_experiment` | experiment harnesses | consume math evidence; no truth promotion | don't fabricate results |
| `JAHS` | mandatory handoff seal | every NMP execute/commit path binds seal; point-0 responses expose it | preserve existing tests |

### 18.1 New modules

Suggested names (not yet implemented):

- `runner_riddle/math_objects.py` — leaf/function/rule/relation dataclasses and canonical serialization.
- `runner_riddle/math_store.py` — BS0DB/MC0DB math persistence and mapping versions.
- `runner_riddle/math_function_registry.py` — semantic contracts over `MthRegistry` implementations.
- `runner_riddle/math_validity.py` — preflight engine and rule-level evaluation.
- `runner_riddle/math_linker.py` — `::` resolver/candidate generator.
- `runner_riddle/nmp.py` — NMP packet/state machine and dedupe.
- `runner_riddle/math_runtime.py` — execution bridge to `MthSystem`/point 0.
- `runner_riddle/mth_pair_file_pages.py` — immutable file-backed 16×16 matrix pages and atomic output generations.
- `runner_riddle/mth_pair_tile_executor.py` — page-backed K16/full-U tile executor and atomic candidate publication (not yet wired to a real guest).
- `spec/math-leaf.schema.json`, `spec/math-function.schema.json`, `spec/math-rule.schema.json`, `spec/nmp.schema.json`.
- tests by the same names plus a new end-to-end demonstration test.

These are proposals; no code in this plan is claimed as implemented.

### 18.2 Proposed API seams

The exact names are negotiable; the separation is not.

```python
# identity / storage
leaf = math_store.put_leaf(content, type, parents, producer)
leaf_v2 = math_store.put_version(leaf.leaf_id, content, parents)
resolved = math_store.resolve(leaf_ref, required_version=None)

# semantic function registry
contract = math_functions.require("math.vector.dot.v1")
plan = math_functions.compose([contract_a, contract_b])

# `::`
candidates = math_linker.propose(
    [ref_a, ref_b],
    snapshot_id=snapshot,
    objective="association",
    max_candidates=8,
    execute=False,
)

# validity authority
preflight = math_validity.preflight(candidates.items[0], snapshot)
# preflight.result is VALID/INVALID/UNDEFINED/UNAUTHORIZED/UNSUPPORTED/
# UNAVAILABLE/STALE/EXPERIMENTAL/UNKNOWN; it is never a numerical answer.

# NMP / execution
packet = nmp.prepare(candidates.items[0], preflight, resources=...)
job = math_runtime.submit(packet, submit_token=..., plan_digest=..., admission_id=...)
result = math_runtime.wait_or_lease(job)   # no host math
leaf = math_store.commit_result(packet, result, provenance=...)
```

Compiler responsibilities:

- selected candidate + contract -> one or more `MthPlanStep` entries;
- workspace sum -> conservative `MthPlan` bound;
- preflight digest and rule snapshot -> job payload;
- capability/implementation -> runner/point-0 route;
- output contract -> new leaf type;
- evidence -> BS0DB event and MC0DB index.

No method named `execute_unchecked`, `force_preflight`, or `host_eval` should exist in this API.

### 18.3 Current implementation gaps this plan must close

These are actual seams in the current code, not hypothetical risks:

| Gap | Current behavior | Required integration |
|---|---|---|
| NMP does not exist | no `nmp.py`/packet state | add host-control packet/state projection over `WaveStore` jobs/leases |
| capability is not enforced at lease | `MthSystem.lease()` checks slot/JAHS, not `dispatchable_capabilities` | per-runner capability/digest/workspace/precision/epoch check before lease |
| preflight is not on execution path | `live_preflight` is read-only/offline | bind `preflight_digest` into NMP/job and check before executor |
| ring lease not registered | `MthSystem.lease()` does not call scheduler `register_lease`/`reserve_memory` | register/release ring lease/memory; `cycle()` must see live work |
| ring epoch not durable | scheduler restarts reset epoch to 1; `complete()` does not check ring | add `ring_incarnation`/persisted epoch and binding on lease/complete |
| all slots not registered | registration tool defaults to R0 only | register capabilities for all six slots or repeated runner IDs |
| `::` is traversal only today | address grammar has no conjunction vs composition dedupe across selectors | math linker uses separate context; add cross-selector duplicate rejection |
| result generation can be newer | `complete_job` accepts `result_generation >` job generation | equality by default; explicit `allow_newer` only |
| cancellation absent | `fail_job` is terminal; no cancel API | add queued cancel + cooperative plan-step cancellation |
| operator default active | `WaveStore.register_operator` defaults to `active` | new math registration defaults to candidate; explicit activation CAS |
| capability digest is caller-supplied | `register_capability(verified_digest=...)` | verify signed fixture/CI envelope bound to source/fixture digests |
| `::` duplicate selectors | address parser dedupes within one list, not across selector items | reject duplicate conjunctions across the expanded set |
| point-0 doc arithmetic | docs say 131,072 words × 8 = 524,288 bytes; code computes 1,048,576 | fix docs; 2 MiB target makes it 262,144 words |
| NANNET0 as lane | no current mapping, but easy to confuse | explicitly lane 0..254; NANNET0 is ring position 255, not a lane |
| plan workspace is summed | `MthRegistry`/`MthSystem` sum step workspace; conservative, can reject a live-buffer plan | compute peak-liveness across the DAG; keep sum fallback only when liveness is undeclared |
| capability workspace at 1 MiB | `wave_capability.workspace` rows registered at 131,072 | migrate/re-register at 262,144 with a new epoch; 1 MiB capability must not admit 196,608-word jobs |
| payload storage 1 MiB | `WaveStore.max_payload_bytes` is 1 MiB; a 2 MiB frame/page cannot be one blob | add content-addressed chunks or an explicit larger bound with evidence |
| schema version hard reject | `wave_store` rejects any schema version != 1 | add `math_*` tables + separate `math_schema`; do not bump `wave_schema` until a versioned migration/backup test exists |
| page count floor | `guest_budget_pages` floors bytes/page | use `ceil` for non-aligned adjustable words and report slack |
| plan digest is caller-supplied | `MthSystem.submit_plan` accepts `operator_digest`/payload with no semantic plan binding | add `plan_digest` + `admission_id`; hash semantic plan + kernel/source digests; require admission in math mode |
| implementation identity is source-only | registration uses `source_digest`; fixture/ABI/toolchain/policy not bound | add `implementation_digest`; keep source digest as a component |
| v1 plan is opaque | `MthPlan` does not type-check input/output handoffs | keep v1 opaque; add typed pins/TypeSpec in `NmpPlan`/v2; never claim v1 type-checks |
| capability registration is R0-only by default | tool registers one runner slot | register all six slots or repeated runner IDs; verify runner-scoped capability at lease |
| math health absent | `MthSystem.health()` can be green if math engine is broken | add optional math/linker/validity health and degrade if unavailable |
| page-backed executor is not wired to a real guest | `mth_pair_tile_executor` has fake-boundary tests only; file pages are local | provide `NativePairTileGuest`/`CandidatePageStore` adapters, run K16 + full-U, prove atomic publication |
| 2 MiB worker budget is aggregate | page executor's 10-worker arithmetic is not a VM memory fence | declare independent worker slots, pin memory, and test 10/11/12 worker admission |
| covariance descriptor is not forced Hermitian | `wave_aperture` can select eigendecomposition for `covariance` without `hermitian=True` | validity must require `role=covariance ⇒ hermitian=True` or select a general decomposition |
| point-0 doc byte arithmetic | docs say 131,072 words = 524,288 bytes; code uses 8-byte words = 1,048,576 | fix docs; 2 MiB target is 262,144 words |

These are P0/P1 integration tests, not implementation details to defer.

---

## 19. Phased implementation priorities

The order below is deliberate. Do not start a later phase by bypassing a failed earlier gate.

### P0 — Freeze the 2 MiB + authority contract

**Priority:** 0 (blocking).
**Scope:** 2 MiB adjustable guest budget is checked in; finish capability re-registration for all six slots, peak-liveness admission, point-0/HTTP bounds, math schema isolation, and the authority/`::` context split.
**Files:** `runner_riddle/mth_system.py`, `point0_bridge.py`, `tools/register_wave_capabilities.py`, `docs/MTH_SYSTEM_RUNTIME.md`, `docs/MTH_MEMORY_1MIB.md`/new 2 MiB doc, `tests/test_mth_system.py`, `tests/test_point0_bridge.py`.
**Exit:** all P0 tests; no existing test regression; explicit GLT gate.
**Implemented:** P0.1–P0.6 are checked in. Dependent plans are admitted by peak live workspace; undeclared-liveness plans keep the v1 sum. Authority/JAHS execution binding is enforced by `MathExecutionBridge`. GLT-enforced 2 MiB page-limit loading remains unproven.

### P1 — Leaf/identity/storage schema

**Priority:** 1.
**Scope:** define `math-leaf.v1`, canonical serialization, leaf identity/content/version separation, provenance/null/void fields; additive math tables; immutable payload and versioned mapping tests.
**Files:** schemas, `math_objects.py`, `math_store.py`, tests.
**Exit:** T01 metadata, A01–A03; recovery tests.

### P2 — Semantic function registry

**Priority:** 2.
**Scope:** `math-functions.v1`; signatures/domains/preconditions/postconditions/undefined/numerical policy/proof status; bind existing kernels; type-compatible composition; compatibility index.
**Exit:** contract tests, unknown function, mismatch, one function/multiple implementations, existing 61-kernel manifest unchanged.

### P3 — Validity engine and rule levels

**Priority:** 3.
**Scope:** levels 0–3, typed outcomes, preflight cache, contradiction detection, no-bypass gate.
**Exit:** invalid candidates cannot execute; stale rule invalidation; test T01–T06, T10–T12, T15, T16, A06–A08, A13.

### P4 — `::` linker

**Priority:** 4.
**Scope:** resolver, classifier, candidate generation/ranking, bounded candidate sets, address-context rejection, deterministic order, no execution.
**Exit:** vector/vector candidate sets; zero candidate typed null; candidate dedupe; T07/T08; A04–A05.

### P5 — NMP + execution bridge

**Priority:** 5.
**Scope:** NMP packet/states, preflight digest, MthSystem/WaveService/lease/point-0 path, dedupe/in-flight, cancellation, JAHS binding.
**Exit:** one end-to-end dot product leaf; duplicate conjunction reuses result; invalid preflight bypass denied; T14/T19/T20; A09–A12/A19.
**Implemented:** NMP validates immutable native-admission receipts and binds them to a live packet/job/lease/ring/JAHS snapshot. `MathExecutionBridge` binds typed admission, active-ring incarnation/epoch, JAHS, capability, durable job, one lease, cancellation, completion/commit, and restart projection. Seven execution tests plus the P12 demo are green. Native receipt production and native operator dispatch remain external P13 gates.

### P6 — Meta-mapping and durable store

**Priority:** 6.
**Scope:** math tables, mapping CAS/rollback, payload references, cache invalidation, recovery, schema migration.
**Exit:** T17/T18; crash/restart, eviction/recovery, append-only events.

### P7 — Null/void/undefined algebra

**Priority:** 7.
**Scope:** typed leaves and operation semantics; no wildcard; failure feedback.
**Exit:** T09/T11, missing reference vs undefined vs empty, no `NULL==0`.
**Implemented:** `math_absence.py` provides nine distinct states, explicit conjunction tables, missing-reference dominance, and mandatory reason/failure-class leaves; 59 tests.

### P8 — Relations/hyperedges/hypergraphs

**Priority:** 8.
**Scope:** relation schema, roles/order/weights/constraints, membership/incidence, bounded traversal, hyperedge-as-input.
**Exit:** T07/T08 and cycle/depth/fan-out tests.
**Implemented:** `math_relation.py` provides typed schemas/roles/arity/duplicate policy, immutable versions, incidence, bounded nested traversal, and canonical digests; 9 tests.

### P9 — Learning/rule discovery and promotion

**Priority:** 9.
**Scope:** structural/transformational/derivational/relational/operational learning; proposal isolation; proof status; contradiction; transactional promotion; Boolean heads.
**Exit:** T16, A13–A14; no self-promotion; level-0 immutability; rollback.
**Implemented:** `math_learning.py` enforces five orthogonal axes, isolated proposals, independent approval, trusted-checker-only V3/proof, transaction/CAS promotion, negative memory, audit chaining, and utility-only Boolean-head experiment evidence; 20 tests.

### P10 — Scratch, oscillation, pruning, retention

**Priority:** 10.
**Scope:** scratch tiers, oscillation state/budgets, duplicate rediscovery control, retention score, structural pruning, recovery.
**Exit:** T20, A15–A16; no infinite loop; cache eviction recoverable.
**Implemented:** `math_retention.py` provides typed scoring, tier policy, deterministic plans, proof/truth preservation, shadow/apply/rollback/restore, oscillation budgets, duplicate and rewrite-cycle stops; 10 tests.

### P11 — 255 logical lanes and capability-aware ring

**Priority:** 11.
**Scope:** map roles to bounded work queues; work stealing; capability matrix; active-slot-only execution; determinism policy; remote workers optional.
**Exit:** no 255-runner overclaim; capability-unavailable vs null; crash/restart; T14/T19/A09.

### P12 — End-to-end demonstration and evidence

**Priority:** 12.
**Scope:** leaf → `::` → preflight → execute → commit → feed back; full provenance; negative suite.
**Exit:** all T01–T20 and A01–A20 green; demo evidence; no host math.
**Implemented:** `tools/run_math_demo.py` runs the control-plane vertical slice with NMP, active-ring lease, commit, and output feedback; 2 tests. It deliberately labels its executor digest as evidence, not a numeric dot product. Full T01–T20/A01–A20 closure remains tied to P13 evidence where applicable.

### P13 — LM/R7/capacity and live deployment

**Priority:** 13.
**Scope:** real frozen-model/data ablations, R7 held-out experiment, capacity-vs-SNR, live Koyeb/NANNET0, production MC0DB.
**Exit:** real evidence or an explicit blocked/rejected result; no fabricated claim.
**Status:** blocked. No live credentials/volumes, frozen-model/data harness, or held-out experiment is available in this environment. No P13 result is claimed.

---

## 20. Ordered TODO and verification backlog

Priority order is top to bottom. A test is not replaced by a later integration test.

Verification convention:

```sh
python3 -m unittest discover -s tests -v
python3 -m unittest tests.test_mth_system tests.test_wave_store   tests.test_point0_bridge tests.test_wave_capabilities -v
python3 tools/run_mth_fixtures.py
```

New math tests live in `tests/test_math_objects.py`, `tests/test_math_registry.py`, `tests/test_math_validity.py`, `tests/test_math_linker.py`, `tests/test_nmp.py`, `tests/test_math_store.py`, `tests/test_math_absence.py`, `tests/test_math_relation.py`, `tests/test_math_learning.py`, `tests/test_math_retention.py`, `tests/test_math_execution.py`, `tests/test_math_demo.py`, and `tests/test_math_end_to_end.py`. The existing 653-test suite remains a regression gate; no new layer may weaken or replace it.

### 20.1 P0 verification

| Order | ID | Test | Acceptance |
|---:|---|---|---|
| 1 | P0-01 | 2 MiB default words/pages | 262,144 words, 64 pages |
| 2 | P0-02 | 1 MiB override | 131,072 words/32 pages; 2 MiB-only plan rejected |
| 3 | P0-03 | 2 MiB plan boundary | exact budget accepted; +1 word rejected before store mutation |
| 4 | P0-04 | Point-0 frame boundary | 262,144 accepted; 262,145 rejected |
| 5 | P0-05 | Full U+L+out budget | admitted at 2 MiB, rejected at 1 MiB |
| 6 | P0-06 | 512 KiB compatibility | old fixtures still runnable/reject correctly |
| 7 | P0-07 | GLT gate | explicit `glt_1mib`/`glt_2mib` evidence, not inferred |
| 8 | P0-08 | JAHS preservation | lease/point-0/commit still require seal |
| 9 | P0-09 | capability workspace re-registration | 1 MiB capability cannot admit 196,608-word job; epoch-2 2 MiB capability does |
| 10 | P0-10 | point-0/HTTP 2 MiB payload | 262,144 words accepted; 262,145 rejected; HTTP body/envelope limit agrees |
| 11 | P0-11 | math schema isolation | `math_*` tables + `math_schema`; `wave_schema` remains 1 and v1 store tests pass |
| 12 | P0-12 | plan peak-liveness | a two-buffer DAG is admitted by peak, not rejected by naive step sum |
| 13 | P0-13 | page accounting | non-aligned words use ceil; slack is reported; no silent floor |

### 20.2 P1–P2 verification

| Order | ID | Test | Acceptance |
|---:|---|---|---|
| 9 | L-01 | canonical leaf serialization | stable digest across key order/whitespace |
| 10 | L-02 | identity vs content | same content, different leaf IDs/provenance |
| 11 | L-03 | immutability/version | v2 created; v1 recoverable |
| 12 | L-04 | null/void/undefined fields | distinct kinds and reasons |
| 13 | F-01 | function contract load | signature/pre/post/undefined/policy validated |
| 14 | F-02 | implementation binding | missing/revoked/mismatched kernel rejected |
| 15 | F-03 | composition | compatible composition accepted; incompatible rejected |
| 16 | F-04 | one function/multiple implementations | same semantic ID, distinct implementation digests |

### 20.3 P3–P5 verification

| Order | ID | Test | Acceptance |
|---:|---|---|---|
| 17 | V-01 | vector + vector equal dims | valid vector candidate |
| 18 | V-02 | vector + vector unequal dims | INVALID/null |
| 19 | V-03 | dot vector | valid scalar |
| 20 | V-04 | matrix × vector compatible | valid vector |
| 21 | V-05 | matrix × vector incompatible | INVALID/null |
| 22 | V-06 | vector + scalar | INVALID unless registered |
| 23 | V-07 | division by zero | UNDEFINED, not zero/null |
| 24 | V-08 | unknown function ID | REJECTED before execution |
| 25 | V-09 | modified ruleset | old packet retains old snapshot; new packet invalidated/retried |
| 26 | V-10 | invalid preflight bypass | executor/lease rejected |
| 27 | V-11 | stale epoch/lease | rejected before executor |
| 28 | V-12 | capability unavailable | UNAVAILABLE, not NULL |
| 29 | V-13 | preflight cache invalidation | rule/input change misses cache |
| 30 | V-14 | contradiction | affected function blocked; no last-writer choice |
| 31 | K-01 | `::` deterministic candidate set | stable order/digest |
| 32 | K-02 | zero candidate | typed NULL with reason, no execution |
| 33 | K-03 | address context | `nan://` in linker rejected; `math://` in router rejected |
| 34 | K-04 | duplicate conjunction | one execution, subscribers share result |
| 35 | N-01 | NMP invalid transition | PROPOSED→EXECUTING rejected |
| 36 | N-02 | COMMITTED requires output digest/provenance | missing fields rejected |
| 37 | N-03 | cancellation/failure distinction | CANCELLED/FAILED not NULL |
| 38 | N-04 | snapshot binding | stale snapshot result not accepted |

### 20.4 P6–P8 verification

| Order | ID | Test | Acceptance |
|---:|---|---|---|
| 39 | S-01 | mapping CAS | stale update rejected; old pointer active |
| 40 | S-02 | rollback | new mapping event; old version recoverable |
| 41 | S-03 | payload eviction | cache miss reloads canonical payload |
| 42 | S-04 | missing/corrupt payload | reference error, not zero/null |
| 43 | S-05 | append-only evidence | update/delete rejected |
| 44 | R-01 | identical content/different provenance | T17 |
| 45 | R-02 | evicted leaf recovery | T18 |
| 46 | R-03 | hyperedge construction/membership | T07/T08 |
| 47 | R-04 | cycle/depth/fan-out | bounded termination |
| 48 | R-05 | null/void conjunction semantics | T09 explicit, no wildcard |

### 20.5 P9–P12 verification

| Order | ID | Test | Acceptance |
|---:|---|---|---|
| 49 | G-01 | experimental rule isolated | T16; cannot execute in production namespace |
| 50 | G-02 | promotion lifecycle | propose→validate→test→approve→activate |
| 51 | G-03 | level-0 immutability | learned rule cannot overwrite |
| 52 | G-04 | contradiction/blocking | affected scope blocked |
| 53 | G-05 | proof-status discipline | test ≠ proof; no overclaim |
| 54 | O-01 | oscillation budget | depth/fan-out/fuel/candidate limits enforced |
| 55 | O-02 | duplicate rediscovery | content-state key stops no-progress loop |
| 56 | O-03 | retention/pruning | cache eviction does not delete truth |
| 57 | O-04 | scratch non-pollution | scratch leaf not visible/promotable |
| 58 | E-01 | 255 logical lanes vs 6 slots | no claim/behavior of 255 concurrent runners |
| 59 | E-02 | work stealing | only whole packets; capability/snapshot preserved |
| 60 | E-03 | crash/restart | lease/epoch recovery; no duplicate commit |
| 61 | E-04 | determinism policy | same snapshot/input/contract → same canonical result |
| 62 | D-01 | end-to-end demo | leaf→`::`→preflight→execute→commit→feed back |
| 63 | D-02 | full negative suite | T01–T20 + A01–A20 all pass |
| 64 | D-03 | no host math audit | no Python result computation in path |
| 65 | D-04 | evidence/promotion | digest, provenance, JAHS, CI, no fabricated claim |

### 20.6 User T01–T20 coverage

The original T01–T20 map to the above as follows:

| User test | Covered by |
|---|---|
| T01 vector+vector equal | V-01 |
| T02 unequal dims | V-02 |
| T03 dot | V-03 |
| T04 matrix×vector compatible | V-04 |
| T05 incompatible | V-05 |
| T06 vector+scalar | V-06 |
| T07 vector::hyperedge | R-03/K-01 |
| T08 hyperedge::hypergraph | R-03 |
| T09 leaf::VOID | R-05 |
| T10 zero vector dot | V-03 + zero-policy test |
| T11 division by zero | V-07 |
| T12 unknown function | V-08 |
| T13 modified ruleset | V-09 |
| T14 identical conjunction | K-04 |
| T15 invalid scratch attempt | V-10 |
| T16 experimental function | G-01 |
| T17 content vs provenance | L-02/R-01 |
| T18 evicted leaf | S-03/R-02 |
| T19 distributed contract | E-04/E-02 |
| T20 recursive generation | O-01/O-02 |

### 20.7 Semantic oracle for the original T01–T20

The expected state must be typed; a test that only checks "not crash" is insufficient.

| Test | Expected semantic state |
|---|---|
| T01 vector+vector equal | `VALID`, result kind `vector` |
| T02 unequal dimensions | `INVALID` → typed `NULL` with dimension reason; no execution |
| T03 dot | `VALID`, scalar leaf |
| T04 matrix×vector compatible | `VALID`, vector leaf |
| T05 incompatible matrix×vector | `INVALID` → typed `NULL`; no execution |
| T06 vector+scalar | `INVALID` unless an explicit mixed function contract is active |
| T07 vector::hyperedge | candidate set of registered relation functions, or empty typed null |
| T08 hyperedge::hypergraph | candidate set governed by relation schema |
| T09 leaf::VOID | `UNKNOWN` if the object may arrive; reference error if required missing; never numeric zero |
| T10 zero vector dot | `VALID`, scalar zero (not null) |
| T11 division by zero | `UNDEFINED` under the registered division contract |
| T12 unknown function ID | `REJECTED` before preflight/execution |
| T13 modified ruleset | old packet keeps old snapshot; current request becomes `STALE` and must re-preflight |
| T14 identical conjunction | one execution key; subscribers share result; no duplicate commit |
| T15 invalid scratch attempt | `REJECTED` before executor; scratch cannot bypass preflight |
| T16 experimental function | `EXPERIMENTAL`, isolated; no production execution/promotion |
| T17 identical content/different provenance | same content digest, distinct leaf IDs/versions; provenance retained |
| T18 evicted cached leaf | recoverable from canonical store; no zero/null substitution |
| T19 distributed calculation | same contract/snapshot and canonical result; location is evidence only |
| T20 recursive generation | bounded depth/fan-out/fuel; stop/dedupe; no uncontrolled expansion |

### 20.8 Truth/validity/proof and lifecycle tests

These are in addition to T01–T20. They are blocking for any self-modification or promotion claim.

| Order | ID | Test | Acceptance |
|---:|---|---|---|
| 66 | X-01 | axis orthogonality | mutating auth/capability/utility/lifecycle does not change truth/validity/proof; client-set validity rejected |
| 67 | X-02 | validity ladder | no skipped levels; V3 requires checked proof + current dependencies; stale proof drops V3 |
| 68 | X-03 | proof binding | statement/theory/checker/dependency change marks proof stale; no trusted use |
| 69 | X-04 | authorization matrix | no unauthorized action succeeds; failures audited; truth unchanged |
| 70 | X-05 | capability vs truth | true rule without kernel remains true/not dispatchable; wrong kernel cannot promote truth |
| 71 | X-06 | canonicalization | alpha-equivalent forms dedup; non-equivalent/semantic-changing normalization rejected without proof |
| 72 | X-07 | cross-store intent/finalize | injected crash at each phase yields complete commit or complete abort; 0 orphan evidence |
| 73 | X-08 | scratch isolation | scratch cannot network, use production tokens, write live mapping, commit, or activate |
| 74 | X-09 | refutation | refuted rule becomes truth=refuted, validity=0, inactive; counterexample retained; utility cannot override |
| 75 | X-10 | contradiction | seeded contradictions detected; affected rules quarantined; no last-writer choice |
| 76 | X-11 | stale/rollback | stale rules never used; rollback restores mapping digest and is idempotent |
| 77 | X-12 | pruning truth preservation | truth/proof/refutation/audit digest set preserved; no referenced blob deleted |
| 78 | X-13 | oscillation/rewrite cycles | hysteresis/dwell/flip budgets enforced; cyclic rewrites rejected/quarantined |
| 79 | X-14 | duplicate rediscovery | exact/canonical/subsumption dedup; negative memory prevents unchanged rediscovery |
| 80 | X-15 | Boolean head gate | 1,024/1,024 checks; leakage 0; 6 control heads unchanged; shuffled baseline at chance |
| 81 | X-16 | R7/LM no-fabrication | missing/synthetic/underpowered never pass; harness outcome never sets validity/truth |
| 82 | X-17 | self-modification guard | self-approval/checker/policy/ACL/control-head changes denied except Class C |
| 83 | X-18 | audit/replay | proposal→validate→commit→activate→deprecate→prune→restore replay digest deterministic |

### 20.9 Execution/binding tests that must precede 24/7 claims

| Order | ID | Test | Acceptance |
|---:|---|---|---|
| 84 | B-01 | duplicate conjunction across selectors | duplicate rejected before enqueue; zero executor calls |
| 85 | B-02 | stale ruleset at lease/complete | rejected; job not done; no executor |
| 86 | B-03 | invalid preflight never reaches executor | blocked before lease |
| 87 | B-04 | capability unavailable vs null result | unavailable is not a successful null; executor not called |
| 88 | B-05 | ring lease blocks handoff | `cycle()` refuses while a durable lease is live; succeeds after completion |
| 89 | B-06 | restart incarnation fencing | old token/epoch rejected; no double commit; expiry reclaims |
| 90 | B-07 | all six slot capabilities | each active slot can lease after registration; unregistered slot fails |
| 91 | B-08 | result-generation equality | newer generation rejected unless explicit policy |
| 92 | B-09 | cancellation | queued/leased/running/done cancellation semantics; no hard preemption claim |
| 93 | B-10 | batch child jobs | parent has no lease; children independently leased; seal only after all terminal |
| 94 | B-11 | no private NMP table | restart reconstructs state from job/lease rows |
| 95 | B-12 | lane 255/NANNET0 rejection | NANNET0 is not a lane; no learning ACL |
| 96 | B-13 | point-0 payload arithmetic | code/constant/doc agree; 2 MiB target boundary tested |
| 97 | B-14 | candidate batch no promotion | candidate seal is promotion-ineligible until separate gate |
| 98 | B-15 | file-backed page snapshot | all 512 page digests verified; mutated page aborts |
| 99 | B-16 | atomic output generation | stale publisher rejected; candidate discarded on mismatch; CAS head advances once |
| 100 | B-17 | 2 MiB worker admission | 10 K16 workers + reference fit by arithmetic; 11 rejected; physical slots declared/verified |
| 101 | B-18 | page executor full-U cross-check | every tile matches full-U reference; mismatch aborts before publication |
| 102 | B-19 | no canonical page on failure | staging is unpublished; canonical head unchanged |

---

## 21. Risks, contradictions, and decisions required

### 21.1 Open decisions

1. **2 MiB synchronization:** GPT's implementation is authoritative for the guest-budget code; this plan targets 2 MiB but current main still shows 1 MiB.
2. **Digest algorithm:** SHA-256 for v1 compatibility vs BLAKE3 for new leaves. Do not mix without algorithm tags and migration policy.
3. **`::` syntax collision:** route traversal vs linker conjunction. The plan requires separate contexts; owner must confirm.
4. **Leaf IDs:** opaque IDs vs `HW0:123` aliases. The plan recommends opaque `nml:`/`math://` IDs; aliases only with binding records.
5. **Level-2 proof policy:** what certificate types are required before a derived rule can be active.
6. **Rule promotion authority:** which principal/head can promote level-2/3 rules.
7. **Native vs host preflight:** which numeric preconditions require native certificates vs structural checks.
8. **Distributed execution:** when remote workers are allowed; current plan treats them as optional and secondary.
9. **Hypergraph semantics:** list of possible relational schemas; no universal wildcard.
10. **Retention policy:** learning weights and archive policy are deployment choices, not math truth.

### 21.2 Contradictions to prevent

- Treating `::` as addition/authorization.
- Treating a function kernel ID as the semantic function ID.
- Treating a content hash as the leaf identity.
- Treating a typed `NULL` as numerical zero.
- Treating capability-unavailable as invalid math.
- Treating a learned association as a proof.
- Treating 255 logical lanes as 255 concurrent runners.
- Treating 2 MiB as permission to materialize a 65,536² operator.
- Letting a stale preflight or old rule snapshot execute.
- Deleting committed mathematical contents during cache pruning.
- Letting a head self-authorize or self-promote.
- Running a candidate before preflight because it is "obvious."
- Treating `wave_aperture` `covariance` as Hermitian without enforcing the descriptor field; add `role=covariance ⇒ hermitian=True` to validity or select an appropriate decomposition.
- Treating `WaveStore.register_operator`'s default `active` status as authorization; new math registration must default to candidate and require an explicit activation CAS.
- Treating caller-supplied `verified_digest` as proof of execution; require a signed fixture/CI evidence envelope bound to source and fixture digests.
- Claiming capability/preflight gating while `MthSystem.lease()` does not yet call `dispatchable_capabilities()` or a preflight gate.
- Claiming handoff safety while `MthSystem.lease()` does not register a ring lease/memory reservation; `cycle()` can believe the ring is idle.
- Claiming stale-epoch safety across scheduler restart while epoch is reset to 1 and not persisted.
- Claiming exactly-once distributed execution; the correct guarantee is at-least-once execution with exactly-once acceptance.
- Treating 255 logical lanes as 255 resident 1 MiB guests or 255 × 7 GiB.
- Mixing implementation evidence, experiment outcome, lifecycle, and mathematical validity in one status field.

### 21.3 Kill criteria

A design or implementation branch must be rejected if:

- it has an execution path without preflight authorization;
- it needs host mathematics for a load-bearing result;
- it cannot distinguish `NULL`, `UNDEFINED`, `UNAVAILABLE`, and `FAILED`;
- it changes a mathematical rule while an in-flight calculation uses the old snapshot;
- it deletes provenance or makes an old version unrecoverable;
- it claims a capacity/creativity/consciousness result without a real held-out experiment;
- it makes a 2 MiB-only claim without the GLT/guest-budget test.

---

## 22. Final one-page architecture

```
                    LEARNING / EVALUATION HEAD LAYER
                 (propose, rank, learn, prune, never authorize)
                                   |
                                   v
        +------------------ `::` MATH LINKER ------------------+
        | resolve -> classify -> propose candidates -> rank    |
        | never execute, never authorize, never mutate rules   |
        +--------------------------+---------------------------+
                                   |
                                   v
        +------------------ VALIDITY ENGINE ----------------------+
        | type/domain/shape | level 0/1/2/3 | preconditions      |
        | postconditions    | undefinedness | ACL | snapshot    |
        | sole writer of PREFLIGHT AUTHORIZATION                |
        +--------------------------+---------------------------+
                                   |
                                   v
        +------------------ NMP PACKET / STATE MACHINE ----------+
        | created ... proposed ... preflight ... queued ...     |
        | executing ... completed ... committed                 |
        | snapshot, dedupe, fuel, capability, JAHS              |
        +--------------------------+---------------------------+
                                   |
                                   v
        +------------------ MTH SYSTEM / POINT-0 / RING ---------+
        | one active slot; 255 logical lanes; 7 GiB ceiling     |
        | native NaN16 execution; 2 MiB adjustable guest        |
        | lease/epoch/generation; no alternate path             |
        +--------------------------+---------------------------+
                                   |
                                   v
        +------------------ EVIDENCE / STORE ---------------------+
        | BS0DB payloads/events | MC0DB functions/rules/validity |
        | NANNET metadata/routing | runner cache (disposable)    |
        +---------------------------------------------------------+

Mathematical truth is not learned utility.
A function is a contract; a kernel is one implementation.
A leaf is immutable; its mappings are versioned.
A null is not a zero; a void is not a wildcard.
The mind may propose; the validity engine authorizes; capability and scheduling decide where; the runner executes; evidence remembers.
```

---

## Appendix A — Minimal schemas to write next

1. `spec/math-leaf.schema.json`
2. `spec/math-function.schema.json`
3. `spec/math-rule.schema.json`
4. `spec/nmp.schema.json`
5. `spec/math-candidate-set.schema.json`
6. `spec/math-store.schema.json` (additive MC0DB/BS0DB math tables)
7. `spec/math-address.md` (math URI and alias rules)

## Appendix B — First implementation milestone

The first milestone is not a vast catalog. It is:

```
leaf create/read/version
  + function contract resolve
  + validity preflight
  + `::` candidate set
  + NMP selected execution
  + immutable result commit
  + provenance/evidence
```

When that works for `dot`, `norm`, `cosine`, `add`, `subtract`, and `hyperedge construction`, the rest of the architecture has a concrete substrate. Do not start with thousands of functions, a full theorem prover, or a 255-way parallel runtime.

## Appendix C — Minimum rule record

A rule record must preserve the orthogonal axes. At minimum:

```json
{
  "schema": "nanrouter.math-rule.v1",
  "rule_id": "nml:U0:rule:...",
  "version": 1,
  "claim_class": "theorem|heuristic|definition|rewrite|empirical_claim",
  "statement": {"canonical_digest": "...", "raw_digest": "..."},
  "theory": {"id": "...", "version": 1, "assumptions_digest": "...", "consistency": "assumed|checked_relative|unknown|inconsistent"},
  "truth": {"status": "definitional|theorem|refuted|open|independent|unknown", "scope": "relative(theory,assumptions)"},
  "validity": {"level": "V0|V1|V2|V3", "basis": ["...", "..."], "envelope": null, "stale": false},
  "proof": {"status": "none|sketch|candidate|checked|refuted|stale|quarantined", "proof_digest": null, "checker_digest": null},
  "authorization": {"owner": "...", "acl_digest": "..."},
  "capability": {"required_kernels": ["..."], "implementation_digests": ["..."]},
  "utility": {"scope": "...", "lcb": 0.0, "ci": [0.0, 0.0], "n": 0, "seeds": []},
  "lifecycle": {"state": "proposed", "generation": 0, "rollback_to": null},
  "lineage": {"parents": [], "supersedes": null, "origin": "..."},
  "evidence": {"root_digest": "...", "policy_digest": "...", "schema_digest": "..."}
}
```

A client may **claim** a validity level; the validator assigns `earned_validity`. The claimed value can never be used as authority. Until a trusted proof checker exists, production validity is capped at V2 and proof candidates are explicitly unchecked.


## 23. Native preflight gate implementation (2026-11-07)

The first executable gate is implemented at `mth/nan16/mth_preflight_gate.nas`.
It is native NaN16 guest code, not a host-language math implementation.

The gate checks:
- ABI version and exact rule epoch;
- ordered input/output type signature;
- both operand domains against the authoritative rule domain;
- optional equal-dimension shape policy;
- required capability subset against available capabilities;
- minimum proof level and enabled policy;
- eight words (256 bits) of the authoritative rule digest.

It returns status 0 for allow and typed denial statuses 1–9. The caller must bind
the exact candidate, rule epoch, and digest into NMP/lease admission. This
primitive does not replace ACL authorization, numerical definedness, proof
verification, or runner health/capacity checks.

A native guest fixture is added at `mth/tests/mth_preflight_gate_test.nas`.
It checks the accepted descriptor and a stale candidate epoch. The dedicated
workflow `.github/workflows/native-preflight-gate.yml` assembles the fixture
with the canonical NaN0S toolchain and executes it under `nan_cli`. CI evidence
must be observed before claiming the fixture passes.
