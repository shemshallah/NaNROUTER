# MTH 128×128 centrosymmetry certificate

Status: source-written and locally executed with the canonical NaN0S toolchain; CI promotion pending.

## 1. Scope

`mth/nan16/mth_centrosymmetry_128.nas` checks:

```
M[i,j] == M[127-i,127-j]  for all i,j
```

and returns the mismatch count. This is a 128×128 certificate prototype for the fold fast path. The full 255/256 matrix certificate still needs a paged/streaming ABI.

## 2. ABI

| Register | Meaning |
|---|---|
| `r1` | M, 16,384 float32 payloads, row-major 128×128 |
| `r13` | 1 |
| return `r1` | 1 success |
| return `r2` | mismatch count |

Comparison is bitwise payload equality (integer `CMP`), not host float comparison. The matrix is read-only; no output allocation.

## 3. Fixture

`mth/tests/mth_centrosymmetry_128_test.nas` checks:

- zero matrix -> 0 mismatches;
- one asymmetric pair -> 2 mismatches;
- repaired mirror -> 0 mismatches.

Local canonical run:

```
MTH CENTROSYMMETRY 128 PASS
676,252 steps, rc=3/HALT
```

## 4. Limitations

- 128×128 only.
- Bitwise equality means differing NaN payloads count as mismatches.
- No fold transform is applied; this is only a certificate.
- A 255/256 certificate requires a paged/streaming design because one full dense float32 matrix consumes the guest budget.
