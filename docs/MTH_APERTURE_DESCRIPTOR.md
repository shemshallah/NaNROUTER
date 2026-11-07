# Wave aperture descriptor (R5)

Status: descriptor and decomposition selector implemented; the NaN16 SVD/eigendecomposition kernel is still open.

## 1. Purpose

`runner_riddle/wave_aperture.py` names the role of a 255×255 head-only or 256×256 ring-position aperture and selects the required decomposition family before any numerical work:

| Role | Decomposition |
|---|---|
| `state` | SVD, or eigendecomposition if Hermitian |
| `filter` | SVD, or eigendecomposition if Hermitian |
| `memory` | SVD, or eigendecomposition if Hermitian |
| `covariance` | eigendecomposition |
| `coupling` | eigendecomposition if Hermitian, else Schur/SVD |
| `scattering` | SVD |

The descriptor does not compute the decomposition. That remains a NaN16 kernel gate.

## 2. Files

- `runner_riddle/wave_aperture.py`
- `spec/wave-aperture.schema.json`
- `tests/test_wave_aperture.py` — 9 tests.

## 3. Safety rules

- Dimensions are 255 or 256; no arbitrary dense product.
- `rank` must be within the dimensions.
- Operator digest, if present, must be 64 lowercase hex.
- The role is declared before the decomposition; this prevents forcing a Hermitian eigendecomposition on a directed/scattering aperture.

## 4. Evidence

```
python3 -m unittest tests.test_wave_aperture -v
Ran 9 tests
OK
```

## 5. Next gates

1. Implement the 128×128/256×256 power-iteration or Lanczos top-k kernel.
2. Implement QUERY/MATCH/FILTER/DRIVE composition.
3. Measure observability/reachability and capacity versus SNR.
4. Add a colored-noise generator.
