# MTH system registry and planner

Status: read-only registry, manifest validation, tag/workspace resolution, and deterministic plan composition implemented. No kernel is executed by this layer.

## 1. Purpose

`runner_riddle/mth_registry.py` is the system-level contract over the native MTH capability manifest (`spec/wave-capabilities.json`). It answers four control-plane questions:

1. Which MTH kernels are declared, and what source/fixture bytes do they correspond to?
2. Which kernels satisfy a tag, workspace, and CI requirement?
3. Is a proposed ordered plan structurally valid?
4. What does a plan require in total workspace and typed data flow?

It does not compute wave mathematics, assemble NaN16, open SQLite, dispatch jobs, or modify the manifest. The native kernels remain the only math owners.

The R10 baseline is 31 CI-verified kernels. The loader does not hard-code that number: every declared entry is validated. The working manifest may contain later additions, and `resolve()` defaults to the CI-verified subset.

## 2. Files

| File | Role |
|---|---|
| `runner_riddle/mth_registry.py` | descriptor, registry, resolution, plan composition |
| `spec/mth-system.schema.json` | JSON Schema for registry, plan-spec, and plan documents |
| `tests/test_mth_registry.py` | real-manifest and negative-contract tests |
| `docs/MTH_SYSTEM_REGISTRY.md` | this document |

The existing `spec/wave-capabilities.json` remains the single manifest. This layer only reads it.

## 3. Manifest validation

`MthRegistry.load(path, root=None)` validates:

- manifest schema is `nanrouter.wave-capabilities.v1` and `kernels` is a non-empty list;
- every `kernel_id` is unique and matches `mth.<lowercase-name>`;
- `source` and `fixture` are relative paths that stay inside the manifest root and exist as files;
- `source_digest` and `fixture_digest` are computed from file bytes with SHA-256 and emitted as 64 lowercase hex characters;
- `steps` is a positive integer, not a boolean;
- `precision` is one of `float32`, `u16->i32`, `u32`, `q16.16`, `q32.32`;
- `workspace_words` is a non-negative integer;
- `shape` is a non-empty list of positive integer dimensions;
- `status` is `declared`, `source_written`, `native_verified`, `degraded`, or `revoked`;
- `ci_verified` is a boolean;
- optional `version` is a positive integer (default `1`) and optional `tags` are lowercase tag strings.

`root` defaults to the manifest's parent, or its grandparent when the manifest lives in a `spec/` directory. A caller may pass `root=` explicitly for a manifest stored elsewhere.

## 4. Descriptor and registry API

`MthKernelDescriptor` is frozen and carries:

```
kernel_id, version, source, fixture, marker, steps, precision,
workspace_words, shape, status, ci_verified,
source_digest, fixture_digest, tags
```

`MthRegistry` is immutable after loading:

| Method | Contract |
|---|---|
| `load(path, root=None)` | validate and hash the manifest |
| `lookup(kernel_id)` | descriptor or `None` |
| `require(kernel_id)` | descriptor or raise `MthRegistryError` |
| `resolve(tags=..., max_workspace=..., require_ci=True)` | matching descriptors in manifest order |
| `validate_plan(plan)` | validate and return an `MthPlan` |
| `compose(plan_spec)` | build, order, and validate an `MthPlan` |
| `health()` | counts by status, precision, and CI claim |
| `to_dict()` | registry document with descriptor list |

Derived tags are sorted and unique:

```
family:<id segment>       shape:<d1xd2>          ci:verified|ci:unverified
precision:<normalized>    status:<status>        workspace:zero|workspace:bounded
```

`resolve()` uses all-of tag matching. `max_workspace` is inclusive. `require_ci=True` is the default so unverified entries are not dispatch candidates unless the caller explicitly opts in.

## 5. Plan model

`MthPlanStep` contains `name`, `kernel_id`, typed `inputs`, typed `outputs`, and `depends_on`. Typed names are opaque strings such as `f32[256].a`, `q16.16[256]`, or `f32.score`.

Two optional extension fields may be added per step:

| Field | Meaning |
|---|---|
| `input_specs` | positional descriptors for `inputs` |
| `output_specs` | positional descriptors for `outputs` |

`MthPlan` contains an ordered tuple of steps, a total workspace bound, `deterministic=True`, and a version. Optional extension fields are `fuel` and `cancel_after`, both positive integers when declared. `kernel_ids`, `inputs`, and `outputs` are derived properties:

- `inputs` are values consumed by a step but not produced anywhere in the plan (external inputs);
- `outputs` are unique produced names in first-definition order;
- `workspace_words` is a conservative sum over the workspace of every step occurrence.

Typed values are opaque names unless the plan opts into `MthValueDescriptor` metadata. Reusing an output name across steps is allowed so a plan can express an in-place state update; the plan-level output list still contains each name once.

### 5.1 Value descriptors

`MthValueDescriptor` is immutable and declarative only; it carries no numeric payload and performs no conversion:

```
precision   optional PRECISIONS token (float32, q16.16, ...)
shape       optional list of positive dimensions; [] means scalar
layout      optional lowercase layout token (dense, blocked, ...)
domain      optional lowercase domain token (real, complex, ...)
alias_of    optional name of another plan value sharing the same storage
```

Every field is optional. `to_dict()` emits only fields that are set.

## 6. Compatible plan v1 serialization

Old plans and documents are unchanged:

- `input_specs`/`output_specs` are emitted only when non-empty;
- `fuel`/`cancel_after` are emitted only when declared;
- the schema string stays `nanrouter.mth-plan.v1`;
- no manifest entry or kernel descriptor gains a required field;
- `MthPlan.to_dict()` for a plan without extensions has the same keys and values as before.

The extension is a plan-level opt-in. It does not change `spec/wave-capabilities.json`, does not add kernel contract fields, and does not claim numerical verification.

## 7. Composition

A small plan specification looks like this:

```json
{
  "schema": "nanrouter.mth-plan-spec.v1",
  "plan_id": "vector.match.v1",
  "workspace_words": 4,
  "steps": [
    {
      "name": "dot",
      "kernel_id": "mth.vector.dot256.f32",
      "inputs": ["f32[256].a", "f32[256].b"],
      "outputs": ["f32.dot"],
      "depends_on": []
    },
    {
      "name": "norm",
      "kernel_id": "mth.vector.norm256.f32",
      "inputs": ["f32[256].a"],
      "outputs": ["f32.norm"],
      "depends_on": []
    },
    {
      "name": "score",
      "kernel_id": "mth.vector.cosine256.f32",
      "inputs": ["f32[256].a", "f32[256].b", "f32.dot"],
      "outputs": ["f32.score"],
      "depends_on": ["dot"]
    }
  ]
}
```

`compose()` performs a stable topological sort: independent steps keep their input order, while a dependency is moved before its consumer. It then validates the resulting plan.

Validation rejects:

- unknown kernel IDs or an empty step list;
- duplicate step names;
- duplicate names in `depends_on`;
- unknown dependencies, self-dependencies, and cycles;
- dependencies that do not precede their consumer in a manually constructed plan;
- kernels whose status is not `native_verified` or whose manifest CI claim is false;
- a workspace bound below the sum required by the steps;
- invalid typed names, plan identifiers, or unknown spec fields;
- declared handoff, alias, fuel, or cancellation metadata that is invalid or inconsistent.

No numerical result is produced or checked. A structurally valid plan is a contract candidate, not evidence that a kernel is correct.

## 8. Typed handoff, alias, and bounds validation

Handoff validation runs only over metadata the plan actually declares. For each
value produced by an earlier step and consumed by a later step, `precision`,
`shape`, `layout`, and `domain` are compared when both the producer
`output_specs` entry and the consumer `input_specs` entry declare that field.
If one side omits a field, that field is not checked; this is what keeps old
untyped plans valid. A conflicting field fails closed with `MthPlanError`.

The same rule applies when a step redefines an output name in place: two
declared metadata versions of the same value must agree. An undeclared
redefinition leaves the previous declared metadata in force.

`alias_of` names another value in the same plan. The target must exist as a
plan input or output. The alias metadata must agree with every declared
descriptor for the target. Aliasing does not create a value, perform a copy,
or bypass handoff checks.

`fuel` and `cancel_after` are positive integer bounds when declared. Zero,
negative, boolean, or non-integer values are rejected. They are plan bounds;
the executor still owns enforcement and cancellation state.

Stable `MthPlanError.reason` codes:

| Reason | Meaning |
|---|---|
| `invalid_plan` | Generic structural failure (backward-compatible default) |
| `invalid_value_descriptor` | Unknown field, bad precision/shape/layout/domain/alias token |
| `value_descriptor_count_mismatch` | `input_specs`/`output_specs` length differs from inputs/outputs |
| `handoff_precision_mismatch` | Producer and consumer precision disagree |
| `handoff_shape_mismatch` | Producer and consumer shape disagree |
| `handoff_layout_mismatch` | Producer and consumer layout disagree |
| `handoff_domain_mismatch` | Producer and consumer domain disagree |
| `alias_unknown` | `alias_of` does not name a plan value |
| `alias_mismatch` | Alias metadata conflicts with the target's declared metadata |
| `fuel_out_of_bounds` | `fuel` is not a positive integer |
| `cancel_out_of_bounds` | `cancel_after` is not a positive integer |

Example declared handoff:

```json
{
  "name": "score",
  "kernel_id": "mth.vector.cosine256.f32",
  "inputs": ["f32[256].a", "f32[256].b"],
  "outputs": ["f32.score"],
  "depends_on": [],
  "input_specs": [
    {"precision": "float32", "shape": [256], "layout": "dense", "domain": "real"},
    {"precision": "float32", "shape": [256], "layout": "dense", "domain": "real"}
  ],
  "output_specs": [
    {"precision": "float32", "shape": [], "domain": "real"}
  ]
}
```

This validates declarations only. It does not prove that a kernel honours them
and does not perform numeric range or precision conversion checks.

## 9. Health

`health()` returns a token-free, deterministic summary:

```json
{
  "schema": "nanrouter.mth-registry-health.v1",
  "kernels": 0,
  "status": {"native_verified": 0},
  "precision": {"float32": 0},
  "ci": {"verified": 0, "unverified": 0},
  "ci_verified": 0,
  "ci_unverified": 0,
  "native_verified_ci": 0
}
```

The counts above illustrate the shape; actual values come from the loaded manifest. `native_verified_ci` counts entries that satisfy both conditions required by a plan step.

## 10. Safety limits and deferred items

- The CI flag is a manifest declaration. This module does not re-run CI or native fixtures.
- Digests detect local byte changes; they are not signatures and do not establish provenance.
- The JSON Schema validates document structure only. It cannot prove that source files exist, that digests match, or that a plan is numerically sound.
- Manifest paths are constrained to the manifest root. Absolute paths and `..` escapes are rejected.
- The registry is loaded eagerly and is not hot-reloaded when files change.
- Plan composition is pure ordering and validation. It never assembles, executes, or benchmarks a kernel.
- Handoff metadata is declarative. It does not prove kernel conformance, infer conversions, or perform numeric range/error analysis.
- Deferred: descriptor-level input/output port signatures and the `MathFunctionRegistry` semantic contract (`docs/GAME_PLAN_::.md` §6); per-step fuel accounting; runtime enforcement of `fuel`/`cancel_after` in the executor; stride/offset and actual storage-alias analysis.

## 11. Evidence

```
python3 -m unittest tests.test_mth_registry -q
Ran 35 tests
OK

python3 -m unittest tests.test_mth_registry tests.test_mth_system -q
Ran 54 tests
OK
```
