# MTH 256-element cosine similarity

Status: source-written and locally executed with the canonical NaN0S toolchain; CI promotion pending.

## 1. Scope

`mth/nan16/mth_cosine256_f32.nas` computes:

```
cosine = dot(x,y) / (||x|| * ||y||), or 0 if either norm is zero
```

It composes the verified float32 dot and norm primitives. This is an R5 `MATCH` primitive.

## 2. ABI

| Register | Meaning |
|---|---|
| `r1` | x, 256 float32 |
| `r2` | y, 256 float32 |
| `r3` | output, one float32 |
| `r4` | caller scratch, four float32 (`dot`, `norm_x`, `norm_y`, saved return link) |
| `r13` | 1 |
| return | `r1=1` |

The fourth scratch word saves the single-link `r15` return address across the nested dot/norm calls. Without it, the wrapper's `RET` would return to the wrong place.

## 3. Fixture

`mth/tests/mth_cosine256_test.nas` checks:

- `x=y=2` -> cosine `1.0`;
- orthogonal unit impulses -> cosine `0.0`.

Local canonical run:

```
MTH COSINE256 PASS
17,189 steps, rc=3/HALT
```

## 4. Limitations

- 256 positions only.
- No phase-sensitive complex cosine; magnitude/real vectors only.
- Zero-vector policy returns 0 rather than a domain error.
- The wrapper needs the four-word scratch frame because NaN16 `CALL` is single-link.
