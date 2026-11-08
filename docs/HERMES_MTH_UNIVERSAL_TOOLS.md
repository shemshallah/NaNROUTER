# HERMES MTH universal catalog and head-directed tools (v1)

This implementation indexes **all 94 entries** of the existing
`spec/wave-capabilities.json` with the HERMES portal. Source and fixture files
are hashed on load. **91 kernels** have CI-verification claims backed by the
pinned NaN0S fixture workflow and are eligible for bounded plan composition.
The three 2026-11-08 additions (normalize, prefix sum, xorshift64) are
local-only (`ci_verified=false`) and are deliberately not planning-eligible.
Fixture PASS evidence is not a universal dynamic execution ABI or a
mathematical proof certificate. The single source of truth is `MthRegistry`;
no Python mirror of the NaN16 math kernels exists.

## Available in this round

Five general catalog/plan operations and a head-address route operation are
exposed by `runner_riddle.hermes_mth_tools.HermesMthTools`:

| Tool | Effect |
|---|---|
| `mth.catalog` | Paginate all verified MTH kernels (filter by family and tags). |
| `mth.inspect` | Retrieve exact source path, fixture path, SHA-256 hashes, shape, precision, native status, execution mode. |
| `mth.categories` | Discover every registered family and native execution status. |
| `mth.prepare` | Validate a single-kernel typed plan with native workspace bounds. |
| `mth.compose` | Validate a dependency-ordered bounded multi-kernel plan; does not execute. |
| `mth.route` | Traverse a leased HW head to a family or kernel ID. |

Every manifest kernel is available through the read-only catalog and inspect
tools; plan tools reject kernels lacking CI verification. This does **not**
assert that all kernels share a general dynamic calling ABI. At present
`mth_execute.nas` admits program 900/operator 77 (dot) and
program 901/operator 78 (cosine), program 902/operator 79 (vector add),
and program 903/operator 80 (vector subtract). The other kernels have native **fixtures**,
but no generic arbitrary-operand invocation through that dispatcher. Calling
`mth.compose` or `mth.prepare` never fabricates a numerical result,
native execution receipt or mathematics certification.

## Protected portal endpoint

`POST /v1/hermes/mth/call` is available on the NaNROUTER HTTP service when
the existing HERMES lease/delegation configuration is enabled. It requires
the same `RIDDLE_HERMES_DELEGATION_TOKEN` as the HERMES lease endpoint,
a live lease receipt, `installation_id`, and the exact leased `head_index`.
The service verifies the receipt **before** dispatching to a tool.

Example (placeholders are not actual credentials):

```json
{
  "installation_id": "your-nannet-installation-id",
  "receipt": {"...": "previously-issued signed receipt"},
  "head_index": 23,
  "tool": "mth.route",
  "arguments": {"address": "HW0:23::vector"}
}
```

Alternative `mth.route` targets:

- `HW0:23::mth` — family overview.
- `HW0:23::vector` — vector kernel catalog.
- `HW0:23::mth.vector.dot256.f32` — inspect the exact native kernel.

The target head must equal the head bound by the live receipt. The current
native lease contract accepts head indices 0..254; head index 255 is **not**
yet available and must not be silently remapped. A family route is a view
of the catalog, **not** a mutation or data-leaf allocator.

Example plan request:

```json
{
  "installation_id": "your-nannet-installation-id",
  "receipt": {"...": "previously-issued signed receipt"},
  "head_index": 23,
  "tool": "mth.compose",
  "arguments": {
    "plan": {
      "plan_id": "explore.vector",
      "steps": [
        {
          "name": "dot",
          "kernel_id": "mth.vector.dot256.f32",
          "inputs": ["f32.a", "f32.b"],
          "outputs": ["f32.dot"],
          "depends_on": []
        }
      ]
    }
  }
}
```

## Resource and safety contracts

- The tool catalog is loaded by hashing actual source and fixture files;
  hashes are provenance identifiers, not mathematical correctness certificates.
- The router production image carries `spec/wave-capabilities.json`,
  `mth/nan16`, and `mth/tests` so verification works after deployment.
- Catalog results are paginated, with at most 100 kernel records per request.
- Composed plans accept at most 64 steps and at most the existing native guest
  workspace limit (2 MiB by default; not the full 8 MiB universe).
- No free-form shell execution, arbitrary guest memory modification, or
  caller-supplied native function pointer is exposed.
- Real execution must subsequently satisfy the existing MathAdmission,
  NMP lease, scheduler and native guest controls. Nothing in this endpoint
  overrides those controls.

## Remaining work for full mathematical experimentation

Universal mathematical *catalog and plan integration* is present; universal
arbitrary-input *execution* is not. Supporting each kernel as a runnable tool
requires a typed input/output ABI, native adapter, workspace layout, bounded
fuel, native receipt, and differential tests against the NaN16 guest for that
kernel. Clay-grade proof work additionally requires independently checked
certificates (e.g., interval enclosures, verified PDE estimates), which
native fixture PASS markers do not establish.

The proposed 8 MiB scratch register universe, durable leaf mutation and
merge-gated BS0/MC0 promotion are separate work; this change does not claim
to implement them.
