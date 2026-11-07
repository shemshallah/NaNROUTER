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

`MthPlan` contains an ordered tuple of steps, a total workspace bound, `deterministic=True`, and a version. `kernel_ids`, `inputs`, and `outputs` are derived properties:

- `inputs` are values consumed by a step but not produced anywhere in the plan (external inputs);
- `outputs` are unique produced names in first-definition order;
- `workspace_words` is a conservative sum over the workspace of every step occurrence.

Typed values are opaque names, not a type checker. Reusing an output name across steps is allowed so a plan can express an in-place state update; the plan-level output list still contains each name once.

## 6. Composition

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
- invalid typed names, plan identifiers, or unknown spec fields.

No numerical result is produced or checked. A structurally valid plan is a contract candidate, not evidence that a kernel is correct.

## 7. Health

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

## 8. Safety limits

- The CI flag is a manifest declaration. This module does not re-run CI or native fixtures.
- Digests detect local byte changes; they are not signatures and do not establish provenance.
- The JSON Schema validates document structure only. It cannot prove that source files exist, that digests match, or that a plan is numerically sound.
- Manifest paths are constrained to the manifest root. Absolute paths and `..` escapes are rejected.
- The registry is loaded eagerly and is not hot-reloaded when files change.
- Plan composition is pure ordering and validation. It never assembles, executes, or benchmarks a kernel.

## 9. Evidence

```
python3 -m unittest tests.test_mth_registry -v
Ran 26 tests
OK
```
