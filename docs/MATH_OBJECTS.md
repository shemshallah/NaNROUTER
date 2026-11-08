# Math object semantic type descriptors (B-09)

Status: implementation note for `B-09` in `docs/MASTER_COMPLETION_TODO.md`.

`MathLeaf` and `MathFunction` records are control-plane objects. The optional
semantic descriptor described here adds type information; it does not evaluate
mathematics, select kernels, or widen the native MTH manifest.

## Placement

A descriptor is not a new top-level record field. It is read from places that
already carry type information:

| Record | Descriptor location |
| --- | --- |
| `MathLeaf` | fields inside `leaf.type` |
| `MathFunction` | each object in `signature.inputs[]`, plus `signature.output` |

This keeps legacy records byte-for-byte compatible. If no descriptor field is
present, `to_dict()` adds no keys and `digest()` is unchanged.

`MathLeaf.type_descriptor` and `MathTypeDescriptor.from_mapping(...)` expose the
validated view. Use `MathTypeDescriptor.to_dict()` when a canonical spelling is
needed.

## Fields

| Canonical field | Accepted aliases | Validation |
| --- | --- | --- |
| `element_type` | `element`, `dtype` | `any`/`*`, or an element token such as `float32`, `i16`, `boolean` |
| `stride` | `strides` | integer `>= 0`, or a list of integers `>= 0` |
| `layout` | none | `any`/`*`, or a lowercase token such as `row_major`, `column_major`, `strided` |
| `units` | `unit` | `any`/`*`, `1`, or a unit expression such as `m`, `m/s`, `m/s^2`, `kg*m/s^2` |
| `rank` | none | integer `>= 0`; when a concrete `shape` is also declared, `rank == len(shape)` |
| `shape` | none | `any`/`*`, or a list of integer dimensions `>= 0` |
| `domain` | none | non-empty string `<= 64` characters (for example `real`, `integer`) |
| `context` | none | JSON object; left opaque by this layer |

Aliases are conveniences. If two aliases for the same field are present with
different values, validation fails instead of silently choosing one. The
original spelling is preserved in record serialization; only the descriptor
view canonicalizes names.

Example leaf:

```python
MathLeaf(
    leaf_id="nml:U0:vector:semantic",
    kind="vector",
    type={
        "element_type": "float32",
        "stride": [1],
        "layout": "row_major",
        "units": "m/s",
        "rank": 1,
        "shape": [256],
        "domain": "real",
        "context": {"frame": "world"},
    },
    content={"digest": "a" * 64, "word_count": 256},
)
```

Example function endpoint:

```python
{
    "name": "a",
    "type": "vector",
    "domain": "real",
    "shape": [256],
    "precision": "float32",
    "element_type": "float32",
    "stride": [1],
    "layout": "row_major",
    "units": "m",
    "rank": 1,
    "context": {"frame": "world"},
}
```

## Compatibility handoff

`MathFunctionRegistry.compose()` now compares these descriptor fields when both
the producer output and consumer input declare them:

- `element_type` (case-insensitive token comparison)
- `stride` (an integer is treated as a one-element stride tuple)
- `layout` (case-insensitive token comparison)
- `units` (textual comparison only)
- `rank` (integer comparison)

A mismatch rejects composition with a reason naming the field. If either side
omits a field, that field is not used to reject the handoff, which preserves
legacy contracts. `any`/`*` matches anything. Existing `type`, `domain`, `shape`,
`precision`, and invariant checks are unchanged:

- `shape` is still strict when the consumer requires a concrete shape.
- `domain` and `precision` still use their existing required-value rules.
- Descriptor fields are included in `compatibility_index()` signature keys.

## Validation

Descriptor validation runs when `MathLeaf` or `MathFunction` is constructed, and
again when a semantic catalogue is loaded by `MathFunctionRegistry`. Invalid
units, strides, layouts, ranks, or conflicting aliases fail closed with a
`MathObjectError` or the registry's catalogue/endpoint error subclass.

The JSON schemas are updated too:

- `spec/math-leaf.schema.json` describes descriptor properties under `type`.
- `spec/math-function.schema.json` defines a shared `endpoint` shape used by
  `signature.inputs[]` and `signature.output`.

## Limitations

- Units are validated for syntax, not dimensionally analysed or converted.
  `m/s` and `m*s^-1` are compatible only if declared identically (or a wildcard
  is used).
- `context` is an opaque JSON object. Keys and meanings are not standardized.
- The descriptor is consumed by object validation and function composition in
  this change. Linker operand matching, validity preflight, storage indexes, and
  discovery still use their existing typed fields; migrating those consumers is
  separate work.
- The leaf schema keeps `type.additionalProperties: true` because relation,
  hypergraph, and other leaf kinds carry their own type payloads.
- Cross-field checks such as `rank == len(shape)` are enforced in Python. The
  JSON schemas describe field-level shapes only.
- Schema tests are structural because this repository does not depend on a
  JSON Schema validator implementation.
