# MTH QUERY / MATCH / FILTER / DRIVE composition

Status: primitive composition documented; no full aperture controller is claimed.

## 1. Available primitives

| Primitive | File | Use |
|---|---|---|
| `dot256` | `mth/nan16/mth_dot256_f32.nas` | projection score, inner product |
| `norm256` | `mth/nan16/mth_norm256_f32.nas` | normalization, residual norm |
| `axpy256` | `mth/nan16/mth_axpy256_f32.nas` | `y += alpha*x`, drive/filter update |
| `cosine256` | `mth/nan16/mth_cosine256_f32.nas` | phase-invariant match score |
| `matvec128` | `mth/nan16/mth_matvec128_f32.nas` | aperture/coupling projection |
| `fold` | `mth/nan16/mth_graph_fold.nas` | guarded symmetry reduction |
| `centrosymmetry128` | `mth/nan16/mth_centrosymmetry_128.nas` | fold certificate |
| `pair` | `mth/nan16/mth_graph_pair.nas` | product-space action |

## 2. QUERY

For a validated basis vector `p` and state `x`:

```
score = dot(x, p)
```

Normalize with `norm256` when comparing across states. A top-k selector, stable tie-break, and basis-version check are still needed for a complete QUERY operation.

## 3. MATCH

For two normalized real vectors, `cosine256` returns the phase-invariant match score. Thresholds must be calibrated against null/shuffled signatures; a score is evidence, not truth.

Phase-sensitive matching requires complex vectors and a shared phase reference; that is not implemented.

## 4. FILTER

A diagonal spectral filter can be applied as an elementwise scale; `axpy256` implements the additive form:

```
y = y + alpha*x
```

A general `y = P g(Λ) P† x` composition needs the aperture basis and is still open.

## 5. DRIVE

A bounded forward drive is an `axpy256` update with a declared energy budget:

```
u = u + dt*f
```

The caller/runner must enforce the energy, rate, and ACL budget before dispatch. Inverse drive (`M c = target`) needs a regularized pseudoinverse and is still open.

## 6. FOLD

Use `centrosymmetry128` to certify a 128×128 matrix before applying the fold. The full 255/256 certificate needs a paged/streaming ABI. A mathematical symmetry is not an authorization symmetry.

## 7. Next gates

1. Native top-k selection with stable tie-breaking.
2. Aperture power iteration/SVD.
3. Complex phase-sensitive MATCH.
4. Bounded inverse DRIVE with pseudoinverse.
5. Full 255/256 fold certificate.
